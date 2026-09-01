"""
Rateio do gabarito pelos trechos.

POR QUE ISTO EXISTE
-------------------
Nas pranchas de laje nervurada uma barra desenhada representa VARIAS barras
iguais, e esse multiplicador nao esta escrito em lugar nenhum legivel: o
texto diz "N20-1Ø12.5 C=830" enquanto a tabela do projeto declara 4 barras
daquela posicao. Medido na prancha real, a razao entre o gabarito e o que
o texto declara vai de 2 a 4,8 - nao e constante, entao nao da para
inventar um fator.

A tabela mestre, por outro lado, traz a quantidade EXATA de cada posicao.
O que ela nao traz e ONDE cada barra esta - e isso o desenho traz.

ENTAO:
    quantidade  <- vem do gabarito (exata)
    localizacao <- vem do desenho (em que trecho a posicao aparece)

Para cada posicao, a quantidade do gabarito e distribuida entre os trechos
na proporcao das barras desenhadas em cada um. Uma posicao com 73 barras
no gabarito que aparece 20 vezes no TRECHO A e 6 no TRECHO BC vira
56,2 barras em A e 16,8 em BC.

CONSEQUENCIAS, ditas com todas as letras:
  - o total por bitola passa a bater com o gabarito por construcao;
  - a DIVISAO entre trechos continua sendo uma estimativa do desenho -
    ela e tao boa quanto a associacao texto/barra;
  - `quantidade_desenho` guarda o que estava escrito, para a coluna de
    conferencia: divergencia grande ali significa que aquela posicao tem
    muita barra igual repetida, ou que o desenho perdeu ocorrencias.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .config import Config
from .log_config import obter_log
from .modelos import (Inconsistencia, PosicaoArmadura, ResultadoProcessamento,
                      Severidade, TipoInconsistencia)


def ratear_por_gabarito(
    posicoes: list[PosicaoArmadura],
    gabarito: list,
    cfg: Config,
    prancha: str,
    resultado: ResultadoProcessamento,
) -> list[PosicaoArmadura]:
    """Substitui as quantidades lidas do desenho pelas do gabarito.

    Recebe as posicoes JA classificadas por trecho e devolve a nova lista.
    O peso nao e recalculado aqui: quem chama roda `calculo.calcular`.
    """
    log = obter_log()
    if not gabarito:
        return posicoes

    est = resultado.estatisticas

    # --- o que o desenho achou, por (posicao, bitola) ------------------
    # A bitola entra na chave porque duas posicoes podem repetir numero
    # em armaduras diferentes da mesma prancha.
    por_chave: dict[tuple[str, float], list[PosicaoArmadura]] = defaultdict(list)
    for p in posicoes:
        por_chave[(p.posicao, round(p.bitola_mm, 3))].append(p)

    novas: list[PosicaoArmadura] = []
    usadas: set[tuple[str, float]] = set()
    nao_localizadas: list = []

    for linha in gabarito:
        chave = (linha.posicao, round(linha.bitola_mm, 3))
        encontradas = por_chave.get(chave)
        qtd_gabarito = float(linha.quantidade)
        # Comprimento unitario do gabarito: e ele que manda no corte e
        # dobra, e e o que garante que o peso feche com o projeto.
        comp_unit = (linha.comprimento_total_cm / qtd_gabarito
                     if qtd_gabarito else 0.0)

        if not encontradas:
            # Posicao existe na tabela do projeto mas NAO foi encontrada no
            # desenho. O programa NAO a inventa no quantitativo: ele reporta
            # o que esta desenhado. Criar a posicao aqui faria o relatorio
            # de um recorte descrever o pavimento inteiro.
            nao_localizadas.append(linha)
            est.posicoes_sem_localizacao += 1
            usadas.add(chave)
            continue

        usadas.add(chave)
        # Proporcao de cada trecho: quanto de barra desenhada caiu nele.
        peso_desenho = sum(max(p.quantidade, 0.0) for p in encontradas)
        if peso_desenho <= 0:
            peso_desenho = float(len(encontradas))
            pesos = [1.0] * len(encontradas)
        else:
            pesos = [max(p.quantidade, 0.0) for p in encontradas]

        d1, reta, d2 = linha.dobra_reta_dobra
        for p, peso in zip(encontradas, pesos):
            fracao = peso / peso_desenho if peso_desenho else 0.0
            p.quantidade_desenho = p.quantidade
            p.quantidade = qtd_gabarito * fracao
            # O comprimento unitario do gabarito manda: e a medida de
            # corte. Junto vem o formato das dobras, que e o que
            # identifica a peca na bancada do dobrador.
            p.comprimento_unit_cm = (linha.comprimento_unitario_cm
                                     or comp_unit or p.comprimento_unit_cm)
            p.pernas_cm = linha.pernas_cm
            p.dobra1_cm, p.reta_cm, p.dobra2_cm = d1, reta, d2
            p.comprimento_variavel = linha.variavel
            p.origem_quantidade = "gabarito"
            novas.append(p)

    # --- posicoes que o desenho tem e o gabarito nao ------------------
    sobrando = [p for chave, lista in por_chave.items() if chave not in usadas
                for p in lista]
    for p in sobrando:
        p.quantidade_desenho = p.quantidade
        p.origem_quantidade = "desenho"
    if sobrando:
        est.posicoes_fora_do_gabarito += len(sobrando)
        exemplos = sorted({f"N{p.posicao}(Ø{p.bitola_mm:g})" for p in sobrando})
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.POSICAO_FORA_DO_GABARITO, Severidade.ALERTA,
            f"{len(sobrando)} posicao(oes) lidas do desenho nao constam na "
            f"tabela mestre desta prancha: {', '.join(exemplos[:8])}"
            f"{'...' if len(exemplos) > 8 else ''}. Entram no quantitativo "
            f"com a quantidade do desenho, entao o total fica ACIMA do "
            f"gabarito nesse valor",
            prancha=prancha, ocorrencias=len(sobrando)))
    novas.extend(sobrando)

    # --- posicoes do projeto que o desenho nao tem --------------------
    if nao_localizadas:
        peso = sum(l.peso_kg for l in nao_localizadas)
        exemplos = ", ".join(f"N{l.posicao}" for l in nao_localizadas[:10])
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.POSICAO_SEM_LOCALIZACAO, Severidade.ALERTA,
            f"{len(nao_localizadas)} posicao(oes) da tabela do projeto "
            f"({peso:,.1f} kg) NAO foram encontradas no desenho e por isso "
            f"NAO entram no quantitativo: {exemplos}"
            f"{'...' if len(nao_localizadas) > 10 else ''}. "
            f"Numa prancha inteira isso indica leitura incompleta; num "
            f"recorte do desenho e o esperado.".replace(",", "."),
            prancha=prancha, ocorrencias=len(nao_localizadas)))

    log.info("  rateio pelo gabarito: %d posicao(oes) do projeto, "
             "%d nao encontradas no desenho, %d fora do gabarito",
             len(gabarito), est.posicoes_sem_localizacao,
             est.posicoes_fora_do_gabarito)
    return novas


def _posicao_sem_local(linha, comp_unit: float, cfg: Config,
                       prancha: str) -> PosicaoArmadura:
    """Cria a posicao que o gabarito tem mas o desenho nao localizou."""
    d1, reta, d2 = linha.dobra_reta_dobra
    return PosicaoArmadura(
        pernas_cm=linha.pernas_cm, dobra1_cm=d1, reta_cm=reta, dobra2_cm=d2,
        comprimento_variavel=linha.variavel,
        id=f"{prancha}-GAB-{linha.posicao}",
        prancha=prancha,
        posicao=linha.posicao,
        quantidade=float(linha.quantidade),
        bitola_mm=linha.bitola_mm,
        comprimento_unit_cm=comp_unit,
        espacamento_cm=None,
        texto_origem=f"(tabela mestre) N{linha.posicao}",
        area=cfg.areas.nome_sem_localizacao,
        sentido=cfg.sentido.nome_indefinido,
        quantidade_desenho=0.0,
        origem_quantidade="gabarito",
    )


# =============================================================================
def aplicar_formato_do_gabarito(
    posicoes: list[PosicaoArmadura], gabarito: list, cfg: Config,
    prancha: str, resultado: ResultadoProcessamento,
) -> None:
    """Traz as DOBRAS da tabela do projeto, sem mexer na quantidade.

    Serve para o caso em que a quantidade vem do desenho (recorte): o
    formato da barra continua sendo uma propriedade da POSICAO, e a
    tabela do projeto e a unica fonte confiavel dele. O numero solto
    desenhado perto da ponta da barra tambem e a dobra, mas ali ele se
    confunde com cota de distribuicao - a tabela nao tem essa ambiguidade.

    A juncao e por (posicao, bitola) e SO e aceita quando o comprimento
    unitario da tabela bate com o C= lido no desenho. Se divergirem, o
    texto e a tabela estao falando de barras diferentes e forcar o
    formato seria inventar dado: a divergencia vira aviso.
    """
    if not gabarito:
        return

    por_chave = {(l.posicao, round(l.bitola_mm, 3)): l for l in gabarito}
    aplicados = 0
    divergentes: list[str] = []
    ausentes: list[str] = []

    for p in posicoes:
        linha = por_chave.get((p.posicao, round(p.bitola_mm, 3)))
        if linha is None:
            ausentes.append(f"N{p.posicao}")
            continue
        if linha.variavel or not linha.comprimento_unitario_cm:
            continue

        # O comprimento e a prova de que e a mesma barra.
        if abs(linha.comprimento_unitario_cm - p.comprimento_unit_cm) > 1.0:
            divergentes.append(
                f"N{p.posicao} (desenho C={p.comprimento_unit_cm:.0f}, "
                f"tabela {linha.comprimento_unitario_cm:.0f})")
            continue

        d1, reta, d2 = linha.dobra_reta_dobra
        p.pernas_cm = linha.pernas_cm
        p.dobra1_cm, p.reta_cm, p.dobra2_cm = d1, reta, d2
        aplicados += 1

    obter_log().info("  formato (dobras) da tabela do projeto aplicado a "
                     "%d de %d posicao(oes)", aplicados, len(posicoes))

    if divergentes:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.COMPRIMENTO_DIVERGE_DO_GABARITO,
            Severidade.ALERTA,
            f"{len(divergentes)} posicao(oes) com comprimento diferente entre "
            f"o texto do desenho e a tabela do projeto: "
            f"{', '.join(divergentes[:6])}"
            f"{'...' if len(divergentes) > 6 else ''}. As dobras NAO foram "
            f"aplicadas nelas - confira qual das duas fontes esta certa",
            prancha=prancha, ocorrencias=len(divergentes)))

    if ausentes:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.POSICAO_FORA_DO_GABARITO, Severidade.ALERTA,
            f"{len(ausentes)} posicao(oes) do desenho nao constam na tabela "
            f"do projeto: {', '.join(sorted(set(ausentes))[:8])}"
            f"{'...' if len(set(ausentes)) > 8 else ''}. Elas entram no "
            f"quantitativo, mas sem as dobras",
            prancha=prancha, ocorrencias=len(ausentes)))
