"""
Orquestracao do pipeline completo.

    conversao -> leitura -> parser -> agrupamento -> associacao
              -> classificacao por area -> calculo

Cada prancha e processada por inteiro antes de passar para a proxima: as
areas de uma prancha so classificam as armaduras daquela mesma prancha.
Isso evita que duas pranchas desenhadas nas mesmas coordenadas (cada uma
com origem em 0,0) misturem trechos entre si.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

from . import agrupamento as ag
from .areas import ClassificadorAreas, desambiguar_nomes
from .associacao import (AssociadorGeometrico, extensao_distribuicao,
                         ponto_representativo)
from .calculo import calcular, conferir_distribuicao, estimar_escala
from .config import Config
from .conversor import coletar_arquivos, preparar_entradas
from .distribuicao import coletar_extensoes, recuperar_quantidades
from .leitura import LeitorDXF, montar_areas
from .log_config import obter_log
from .modelos import (Estatisticas, Inconsistencia, PosicaoArmadura,
                      ResultadoProcessamento, Severidade, TipoInconsistencia)
from .parser_texto import ParserArmadura
from .rateio import aplicar_formato_do_gabarito, ratear_por_gabarito
from .tabela_mestre import LeitorTabelaMestre


def processar(entrada: Path, cfg: Config) -> ResultadoProcessamento:
    """Executa o pipeline sobre um arquivo ou uma pasta de pranchas."""
    log = obter_log()
    inicio = time.perf_counter()
    resultado = ResultadoProcessamento()
    est = resultado.estatisticas

    # ---------------------------------------------------------------- 1
    log.info("=" * 70)
    log.info("ETAPA 1/7 - ENTRADA E CONVERSAO")
    arquivos = coletar_arquivos(entrada)
    log.info("%d arquivo(s) encontrado(s)", len(arquivos))

    dxfs, falhas = preparar_entradas(arquivos, cfg.conversao)
    est.arquivos_convertidos = sum(1 for a in arquivos if a.suffix.lower() == ".dwg")
    for arquivo, motivo in falhas:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.CONVERSAO_FALHOU, Severidade.ERRO,
            f"{motivo}; a prancha NAO foi processada e seu aco esta ausente "
            f"do quantitativo", prancha=arquivo.name,
        ))
    if not dxfs:
        log.error("Nenhum DXF disponivel para leitura.")
        return resultado

    leitor = LeitorDXF(cfg)
    parser = ParserArmadura(cfg)
    nomes_areas_usados: dict[str, int] = {}

    # ---------------------------------------------------------------- 2..6
    for caminho in dxfs:
        try:
            _processar_prancha(caminho, cfg, leitor, parser, resultado,
                               nomes_areas_usados)
        except Exception as exc:
            log.exception("Falha ao processar %s", caminho.name)
            resultado.adicionar(Inconsistencia(
                TipoInconsistencia.CONVERSAO_FALHOU, Severidade.ERRO,
                f"erro ao processar a prancha: {exc}", prancha=caminho.stem,
            ))

    est.tempo_s = time.perf_counter() - inicio
    _registrar_resumo(resultado, cfg)
    return resultado


# =============================================================================
def _processar_prancha(caminho: Path, cfg: Config, leitor: LeitorDXF,
                       parser: ParserArmadura, resultado: ResultadoProcessamento,
                       nomes_usados: dict[str, int]) -> None:
    log = obter_log()
    est = resultado.estatisticas

    log.info("-" * 70)
    conteudo = leitor.ler(caminho)
    resultado.pranchas.append(conteudo.prancha)
    est.arquivos_lidos += 1
    est.entidades_totais += conteudo.total_entidades
    est.geometrias_lidas += len(conteudo.geometrias)

    # A altura mediana do texto desta prancha calibra TODAS as tolerancias.
    cfg.calibrar(conteudo.altura_mediana)
    est.altura_texto_mediana = conteudo.altura_mediana

    # ---------------------------------------------------------------- 3
    log.info("ETAPA 3/7 - PARSER (%d textos)", len(conteudo.textos))
    textos = conteudo.textos
    est.textos_lidos += len(textos) + len(conteudo.textos_fora_filtro)
    est.textos_em_layers_ignoradas += len(conteudo.textos_ignorados)

    posicoes_por_texto: dict[int, list] = {}
    nao_interpretados: set[int] = set()

    for i, t in enumerate(textos):
        r = parser.interpretar(t.conteudo)
        if r.ignorado:
            est.textos_ignorados_ruido += 1
            continue
        if r.posicoes:
            posicoes_por_texto[i] = r.posicoes
            est.textos_interpretados += 1
            est.posicoes_por_layer[t.layer] = est.posicoes_por_layer.get(t.layer, 0) + 1
            for prob in r.problemas:
                resultado.adicionar(Inconsistencia(
                    prob.tipo, prob.severidade, prob.descricao,
                    prancha=t.prancha, layer=t.layer, handle=t.handle,
                    texto=t.conteudo, x=t.x, y=t.y))
        else:
            nao_interpretados.add(i)

    # ---------------------------------------------------------------- 4a
    log.info("ETAPA 4/7 - AGRUPAMENTO (tolerancia %.3f unidades)", cfg.tol_agrupamento)
    grupos = ag.agrupar(textos, cfg)
    dist = ag.estatisticas_grupos(grupos)
    log.info("  %d grupos; tamanhos %s", len(grupos), dist)

    # Remontagem de textos que o CAD quebrou em dois pedacos.
    if cfg.agrupamento.juntar_fragmentos and nao_interpretados:
        antes = len(nao_interpretados)
        for grupo in grupos:
            if not (set(grupo.indices) & nao_interpretados):
                continue
            juncoes = ag.remontar_fragmentos(
                grupo, textos, nao_interpretados,
                lambda s: bool(parser.interpretar(s).posicoes),
            )
            for a, b, junto in juncoes:
                r = parser.interpretar(junto)
                if not r.posicoes:
                    continue
                posicoes_por_texto[a] = r.posicoes
                nao_interpretados.discard(a)
                nao_interpretados.discard(b)
                textos[a].conteudo = junto
                est.textos_interpretados += 1
        if antes != len(nao_interpretados):
            log.info("  %d fragmento(s) remontado(s)", antes - len(nao_interpretados))

    for i in sorted(nao_interpretados):
        t = textos[i]
        est.textos_nao_interpretados += 1
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.TEXTO_NAO_INTERPRETADO, Severidade.ERRO,
            "nenhum padrao do config.yaml casou; este aco NAO esta no "
            "quantitativo",
            prancha=t.prancha, layer=t.layer, handle=t.handle,
            texto=t.conteudo, x=t.x, y=t.y))

    # Rede de seguranca: armadura em layer que o filtro deixou de fora.
    _checar_layers_nao_lidas(conteudo, parser, resultado)

    # ---------------------------------------------------------------- 4b
    log.info("ETAPA 5/7 - ASSOCIACAO TEXTO-BARRA (raio %.3f unidades)",
             cfg.raio_associacao)
    associador = AssociadorGeometrico(conteudo.geometrias, cfg)
    est.geometrias_barra += len(associador.barras)
    log.info("  %d geometrias qualificadas como barra", len(associador.barras))

    associacoes: dict[int, object] = {}
    for grupo in grupos:
        # So vale associar grupos que contenham texto interpretado.
        if not (set(grupo.indices) & posicoes_por_texto.keys()):
            continue
        for a in associador.associar_grupo(grupo, textos):
            associacoes[a.indice_texto] = a

    # ---------------------------------------------------------------- 5
    log.info("ETAPA 6/7 - CLASSIFICACAO POR AREA")
    areas, incs_area = montar_areas(conteudo, cfg, len(resultado.areas),
                                    e_armadura=parser.nao_serve_como_rotulo)
    for inc in incs_area:
        resultado.adicionar(inc)
    desambiguar_nomes(areas, nomes_usados)
    resultado.areas.extend(areas)
    est.areas_encontradas += len(areas)
    log.info("  %d area(s): %s", len(areas),
             ", ".join(a.nome for a in areas) or "(nenhuma)")
    classificador = ClassificadorAreas(areas, cfg)

    # ---------------------------------------------------------------- 6
    log.info("ETAPA 7/7 - CALCULO")
    novas: list[PosicaoArmadura] = []
    for i, brutas in posicoes_por_texto.items():
        t = textos[i]
        assoc = associacoes.get(i)
        barra = (associador.barras[assoc.indice_barra]
                 if assoc is not None and assoc.indice_barra is not None else None)

        if barra is None:
            est.associacoes_falharam += 1
            resultado.adicionar(Inconsistencia(
                TipoInconsistencia.TEXTO_SEM_GEOMETRIA, Severidade.ALERTA,
                "nenhuma barra encontrada no raio de busca; a posicao entra "
                "no quantitativo classificada pelo ponto do texto",
                prancha=t.prancha, layer=t.layer, handle=t.handle,
                texto=t.conteudo, x=t.x, y=t.y))
            if not cfg.associacao.usar_ponto_texto_se_falhar:
                continue
        elif assoc.duvidosa:
            est.associacoes_duvidosas += 1
            resultado.adicionar(Inconsistencia(
                TipoInconsistencia.ASSOCIACAO_DUVIDOSA, Severidade.ALERTA,
                f"associacao texto-barra com score {assoc.score:.2f} "
                f"(limite {cfg.associacao.score_suspeito:.2f}); confira no CAD "
                f"se o texto pertence mesmo a esta barra",
                prancha=t.prancha, layer=t.layer, handle=t.handle,
                texto=t.conteudo, x=t.x, y=t.y))
        else:
            est.associacoes_ok += 1

        xr, yr = ponto_representativo(barra, t)
        fatias = classificador.classificar(
            xr, yr, barra.geometria if barra is not None else None)

        for bruta in brutas:
            for nome_area, fracao in fatias:
                if fracao <= 0:
                    continue
                pos = PosicaoArmadura(
                    id=f"{t.handle}-{bruta.posicao}-{nome_area}",
                    prancha=t.prancha, posicao=bruta.posicao,
                    quantidade=bruta.quantidade, bitola_mm=bruta.bitola_mm,
                    comprimento_unit_cm=bruta.comprimento_cm,
                    espacamento_cm=bruta.espacamento_cm,
                    texto_origem=bruta.texto_origem, observacao=bruta.observacao,
                    quantidade_explicita=bruta.quantidade_explicita,
                    comprimento_variavel=bruta.comprimento_variavel,
                    x_texto=t.x, y_texto=t.y, handle_texto=t.handle,
                    layer_texto=t.layer,
                    handle_barra=barra.handle if barra else None,
                    geometria_barra=barra.geometria if barra else None,
                    x_repr=xr, y_repr=yr,
                    angulo_barra=barra.angulo if barra else None,
                    sentido=cfg.sentido.classificar(
                        barra.angulo if barra else None),
                    score_associacao=assoc.score if assoc else None,
                    associacao_duvidosa=bool(assoc and assoc.duvidosa),
                    area=nome_area, fracao_area=fracao,
                )
                inc = calcular(pos, cfg)
                if inc:
                    resultado.adicionar(inc)
                novas.append(pos)
                if nome_area == cfg.areas.nome_sem_area:
                    est.posicoes_sem_area += 1

    # ATENCAO A ORDEM: as posicoes so entram em `resultado` DEPOIS do
    # rateio. Entregar antes faria o rateio trabalhar sobre uma lista ja
    # publicada, e tudo que ele criasse ou removesse seria descartado em
    # silencio.

    # ---- conferencia opcional contra a linha de distribuicao ---------
    escala = estimar_escala(novas)
    if escala:
        est.escala_estimada = escala
        log.info("  escala estimada: 1 unidade de desenho = %.1f cm reais", escala)
        vistos: set[str] = set()
        for pos in novas:
            if pos.handle_texto in vistos or pos.geometria_barra is None:
                continue
            vistos.add(pos.handle_texto)
            barra = next((b for b in associador.barras
                          if b.handle == pos.handle_barra), None)
            ext = extensao_distribuicao(barra, conteudo.geometrias, cfg)
            inc = conferir_distribuicao(pos, ext, escala, cfg)
            if inc:
                resultado.adicionar(inc)

    # ---- tabela mestre desenhada na prancha (gabarito) ---------------
    gabarito = []
    if cfg.tabela_mestre.ativar and conteudo.textos_tabela:
        gabarito, avisos = LeitorTabelaMestre(cfg).ler(
            conteudo.textos_tabela, parser.normalizar)
        resultado.tabela_mestre.extend(gabarito)
        est.linhas_tabela_mestre += len(gabarito)
        est.peso_tabela_mestre_kg += sum(l.peso_kg for l in gabarito)
        for aviso in avisos:
            resultado.adicionar(Inconsistencia(
                TipoInconsistencia.TABELA_MESTRE, Severidade.ALERTA, aviso,
                prancha=conteudo.prancha))

    # ---- quantidade das barras distribuidas sem numero escrito -------
    # Feito ANTES de decidir a fonte da quantidade: a proporcao usada no
    # rateio tambem fica mais fiel quando cada barra distribuida sabe
    # quantas ela representa.
    recuperar_quantidades(
        novas, coletar_extensoes(conteudo.textos_distribuicao, cfg),
        cfg, conteudo.prancha, resultado)
    for pos in novas:
        calcular(pos, cfg)

    # ---- de onde vem a quantidade ------------------------------------
    if _usar_gabarito(cfg, gabarito, novas, resultado, conteudo.prancha):
        novas = ratear_por_gabarito(novas, gabarito, cfg, conteudo.prancha,
                                    resultado)
        for pos in novas:
            inc = calcular(pos, cfg)
            if inc:
                resultado.adicionar(inc)
    else:
        for pos in novas:
            pos.quantidade_desenho = pos.quantidade
            pos.origem_quantidade = "desenho"
        # A quantidade veio do desenho, mas o FORMATO da barra (dobras)
        # continua vindo da tabela do projeto: e propriedade da posicao,
        # nao da quantidade, e sem ele a planilha nao serve para corte
        # e dobra.
        aplicar_formato_do_gabarito(novas, gabarito, cfg, conteudo.prancha,
                                    resultado)

    est.posicoes_geradas += len(novas)
    resultado.posicoes.extend(novas)

    # ---- armaduras fora de qualquer area -----------------------------
    # INFO, nao ALERTA: estar fora dos contornos e uma situacao normal de
    # projeto (o contorno delimita o trecho que se quer medir), nao um
    # defeito de leitura. O aco continua inteiro no RESUMO GERAL.
    sem_area = [p for p in novas if p.area == cfg.areas.nome_sem_area]
    if sem_area:
        peso = sum(p.peso_com_perda_kg for p in sem_area)
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.BARRA_SEM_AREA, Severidade.INFO,
            f"{len(sem_area)} posicao(oes) fora de qualquer poligono da layer "
            f"AREA, somando {peso:,.1f} kg (com perda). Entram no RESUMO GERAL "
            f"e na aba '{cfg.areas.nome_sem_area}'",
            prancha=conteudo.prancha, layer="AREA", ocorrencias=len(sem_area),
        ))

    # ---- barras cortadas pelo contorno -------------------------------
    # NAO gera inconsistencia: e o comportamento pedido do criterio
    # `fora_do_escopo`. Fica so na estatistica e no log.
    cortadas = [p for p in novas if p.area == cfg.areas.nome_fora_escopo]
    if cortadas:
        peso = sum(p.peso_com_perda_kg for p in cortadas)
        est.posicoes_fora_escopo += len(cortadas)
        log.info("  %d posicao(oes) cortadas pelo contorno da AREA "
                 "(%.1f kg com perda) -> %s", len(cortadas), peso,
                 cfg.areas.nome_fora_escopo)

    log.info("  %d posicao(oes) geradas nesta prancha", len(novas))


# =============================================================================
def _usar_gabarito(cfg: Config, gabarito: list, posicoes: list,
                   resultado: ResultadoProcessamento, prancha: str) -> bool:
    """Decide se a quantidade vem da tabela do projeto ou do desenho.

    O rateio pelo gabarito existe porque, numa prancha inteira, uma barra
    desenhada representa varias barras iguais e o texto subconta. Mas a
    tabela descreve o PAVIMENTO INTEIRO. Se o DXF for um recorte - poucas
    barras desenhadas, tabela completa - ratear jogaria o pavimento todo
    em cima das poucas barras presentes (uma barra virando 609).

    O criterio e a COBERTURA: quantas posicoes da tabela aparecem no
    desenho. Prancha inteira cobre quase tudo; recorte cobre pouco.
    """
    log = obter_log()
    modo = cfg.calculo.fonte_quantidade
    if modo == "desenho" or not gabarito:
        return False
    if modo == "gabarito_rateado":
        return True

    # modo automatico
    no_gabarito = {(l.posicao, round(l.bitola_mm, 3)) for l in gabarito}
    no_desenho = {(p.posicao, round(p.bitola_mm, 3)) for p in posicoes}
    encontradas = len(no_gabarito & no_desenho)
    cobertura = encontradas / len(no_gabarito) if no_gabarito else 0.0

    if cobertura >= cfg.calculo.limiar_recorte:
        log.info("  quantidade: TABELA DO PROJETO (cobertura %.0f%% - o "
                 "desenho tem quase todas as posicoes da tabela)",
                 cobertura * 100)
        return True

    log.info("  quantidade: DESENHO (cobertura %.0f%% - o desenho tem so "
             "%d das %d posicoes da tabela; parece um recorte)",
             cobertura * 100, encontradas, len(no_gabarito))
    resultado.adicionar(Inconsistencia(
        TipoInconsistencia.RECORTE_DETECTADO, Severidade.ALERTA,
        f"o desenho tem {encontradas} das {len(no_gabarito)} posicoes da "
        f"tabela do projeto ({cobertura * 100:.0f}%). A tabela descreve o "
        f"pavimento inteiro, entao ela NAO foi usada como fonte da "
        f"quantidade - o relatorio traz o que esta DESENHADO. Se esta e "
        f"uma prancha inteira e nao um recorte, a leitura esta incompleta: "
        f"revise layers.texto_armadura no config.yaml",
        prancha=prancha, ocorrencias=len(no_gabarito) - encontradas))
    return False


# =============================================================================
def _checar_layers_nao_lidas(conteudo, parser: ParserArmadura,
                             resultado: ResultadoProcessamento) -> None:
    """Avisa quando ha texto com cara de armadura em layer fora do filtro.

    Sem isto, apertar demais `layers.texto_armadura` faria o programa
    perder posicoes em silencio - o pior tipo de erro num quantitativo.
    """
    suspeitos: Counter[str] = Counter()
    exemplos: dict[str, str] = {}
    for t in conteudo.textos_fora_filtro:
        if parser.parece_armadura(t.conteudo):
            suspeitos[t.layer] += 1
            exemplos.setdefault(t.layer, t.conteudo)

    for layer, n in suspeitos.items():
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.TEXTO_EM_LAYER_NAO_LIDA, Severidade.ALERTA,
            f"{n} texto(s) com formato de armadura na layer '{layer}', que nao "
            f"consta em layers.texto_armadura. Exemplo: {exemplos[layer]!r}. "
            f"Se for armadura de verdade, inclua a layer no config.yaml",
            prancha=conteudo.prancha, layer=layer, ocorrencias=n,
            texto=exemplos[layer],
        ))


def _registrar_resumo(resultado: ResultadoProcessamento, cfg: Config) -> None:
    """Escreve o balanco final no log e como linha informativa do relatorio."""
    log = obter_log()
    e = resultado.estatisticas
    peso = sum(p.peso_com_perda_kg for p in resultado.posicoes)
    liquido = sum(p.peso_liquido_kg for p in resultado.posicoes)

    log.info("=" * 70)
    log.info("RESUMO DO PROCESSAMENTO")
    log.info("  arquivos lidos ............... %d", e.arquivos_lidos)
    log.info("  entidades no desenho ......... %d", e.entidades_totais)
    log.info("  textos lidos ................. %d", e.textos_lidos)
    log.info("    interpretados .............. %d", e.textos_interpretados)
    log.info("    ruido descartado ........... %d", e.textos_ignorados_ruido)
    log.info("    em layers ignoradas ........ %d", e.textos_em_layers_ignoradas)
    log.info("    NAO interpretados .......... %d", e.textos_nao_interpretados)
    log.info("  geometrias lidas ............. %d", e.geometrias_lidas)
    log.info("    qualificadas como barra .... %d", e.geometrias_barra)
    log.info("  associacoes ok ............... %d", e.associacoes_ok)
    log.info("    duvidosas .................. %d", e.associacoes_duvidosas)
    log.info("    sem barra .................. %d", e.associacoes_falharam)
    log.info("  areas encontradas ............ %d", e.areas_encontradas)
    log.info("  posicoes geradas ............. %d", e.posicoes_geradas)
    log.info("    fora de qualquer area ...... %d", e.posicoes_sem_area)
    log.info("    cortadas pelo contorno ..... %d", e.posicoes_fora_escopo)
    if e.linhas_tabela_mestre:
        log.info("  tabela mestre do desenho ..... %d linhas, %.1f kg",
                 e.linhas_tabela_mestre, e.peso_tabela_mestre_kg)
    log.info("  PESO LIQUIDO ................. %.1f kg", liquido)
    log.info("  PESO COM PERDA (%.0f%%) ........ %.1f kg",
             cfg.calculo.perda_percentual * 100, peso)
    log.info("  tempo ........................ %.1f s", e.tempo_s)
    log.info("=" * 70)

    if e.textos_ignorados_ruido:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.RESUMO, Severidade.INFO,
            f"{e.textos_ignorados_ruido} texto(s) descartados por casarem com "
            f"parser.ignorar_textos (numeros soltos de cota de dobra, titulos, "
            f"escalas). Se faltar aco no total, revise essa lista no config.yaml",
            ocorrencias=e.textos_ignorados_ruido,
        ))
