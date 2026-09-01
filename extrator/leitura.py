"""
Leitura do DXF: entidades do CAD viram objetos de dominio.

Responsabilidades:
  - percorrer Model Space (e Layouts, se pedido), explodindo blocos;
  - separar textos, geometrias de barra e contornos da layer AREA;
  - montar poligonos fechados, inclusive a partir de LINEs soltas;
  - medir a altura mediana do texto, que calibra todas as tolerancias.

Nada aqui interpreta o conteudo do texto - isso e do parser_texto.
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Iterator, Optional

import ezdxf
from ezdxf.entities import DXFEntity
from ezdxf.path import make_path
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

import re

from .config import Config, casa_padrao, normalizar_nome
from .log_config import obter_log
from .modelos import (AreaProjeto, GeometriaDXF, Inconsistencia, Severidade,
                      TextoDXF, TipoInconsistencia)

# Tipos que podem representar o desenho de uma barra.
TIPOS_GEOMETRIA = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "SPLINE", "ELLIPSE"}
TIPOS_TEXTO = {"TEXT", "MTEXT"}

# Layers genericas demais para nomear um trecho: se todas as regioes
# estiverem numa unica layer 'AREA', o nome tem de vir de outra fonte.
_LAYERS_GENERICAS = {"AREA", "AREAS", "0", "TRECHO", "TRECHOS"}


class LeitorDXF:
    """Le um arquivo DXF e devolve as entidades ja classificadas."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.log = obter_log()

    # ------------------------------------------------------------------
    def ler(self, caminho: Path) -> "ConteudoPrancha":
        """Le uma prancha inteira."""
        prancha = caminho.stem
        self.log.info("Lendo %s", caminho.name)
        try:
            doc = ezdxf.readfile(str(caminho))
        except (IOError, ezdxf.DXFStructureError) as exc:
            raise ValueError(f"DXF ilegivel ({caminho.name}): {exc}") from exc

        self.log.debug("  versao DXF %s (%s)", doc.dxfversion, doc.acad_release)

        entidades = list(self._percorrer(doc))
        self.log.info("  %d entidades (blocos ja explodidos)", len(entidades))

        conteudo = ConteudoPrancha(prancha=prancha, total_entidades=len(entidades))

        # --- 1a passada: textos (precisamos da altura mediana antes de tudo)
        brutos_texto: list[tuple[DXFEntity, str, float, float, float, float]] = []
        alturas: list[float] = []
        for e in entidades:
            if e.dxftype() not in TIPOS_TEXTO:
                continue
            for texto, x, y, h, rot in self._extrair_textos(e):
                brutos_texto.append((e, texto, x, y, h, rot))
                if h > 0:
                    alturas.append(h)

        # A altura mediana calibra tolerancia de agrupamento, raio de busca,
        # comprimento minimo de barra e area minima de poligono. E o que
        # torna o mesmo config.yaml valido em pranchas de escalas diferentes.
        if alturas:
            conteudo.altura_mediana = statistics.median(alturas)
            self.log.info("  altura mediana do texto: %.4f unidades",
                          conteudo.altura_mediana)
        else:
            conteudo.altura_mediana = 1.0
            self.log.warning("  nenhum texto com altura; tolerancias usarao 1.0")

        for e, texto, x, y, h, rot in brutos_texto:
            layer = e.dxf.layer
            t = TextoDXF(
                handle=str(e.dxf.handle), conteudo=texto, conteudo_bruto=texto,
                x=x, y=y, altura=h or conteudo.altura_mediana,
                rotacao=rot % 360.0, layer=layer, prancha=prancha,
            )
            if self.cfg.layers.e_texto_armadura(layer):
                conteudo.textos.append(t)
            elif not self.cfg.layers.e_ignorada(layer):
                # Layer nao ignorada mas fora do filtro de armadura:
                # guardada para a checagem de "armadura em layer nao lida".
                conteudo.textos_fora_filtro.append(t)
            else:
                conteudo.textos_ignorados.append(t)

            # A tabela de aco desenhada na prancha continua FORA do
            # quantitativo (senao o aco entraria duas vezes), mas e
            # guardada a parte: e o gabarito da conferencia.
            if casa_padrao(layer, self.cfg.tabela_mestre.layers):
                conteudo.textos_tabela.append(t)

            # Rotulos com a extensao da distribuicao: numeros soltos ao
            # lado da barra, de onde sai a quantidade das armaduras
            # escritas com espacamento e sem numero de barras.
            if casa_padrao(layer, self.cfg.layers.texto_distribuicao):
                conteudo.textos_distribuicao.append(t)

        # --- 2a passada: geometria -------------------------------------
        tol_simplif = self.cfg.leitura.tolerancia_simplificacao_rel * conteudo.altura_mediana
        # Segmentos e aneis sao guardados POR LAYER: cada trecho e
        # desenhado na sua propria layer (TRECHO 01, TRECHO 02...) e a
        # poligonizacao precisa ser feita layer a layer. Juntar tudo
        # faria segmentos de trechos vizinhos formarem um poligono que
        # nao existe no projeto.
        segmentos_area: dict[str, list[LineString]] = {}
        aneis_area: list[tuple[Polygon, str, bool, str]] = []

        for e in entidades:
            tipo = e.dxftype()
            if tipo not in TIPOS_GEOMETRIA:
                continue
            layer = e.dxf.layer

            pontos = self._pontos(e, tol_simplif)
            if len(pontos) < 2:
                continue

            # ---- contorno de AREA -------------------------------------
            if self.cfg.layers.e_area(layer):
                fechado = self._esta_fechado(e, pontos)
                if fechado and len(pontos) >= 4:
                    try:
                        poli = Polygon(pontos)
                        if not poli.is_valid:
                            poli = poli.buffer(0)
                        if poli.area > 0:
                            aneis_area.append(
                                (poli, str(e.dxf.handle), False, layer))
                            continue
                    except (ValueError, TypeError):
                        pass
                # Nao fechou sozinho: vira segmento para a poligonizacao.
                segmentos_area.setdefault(layer, []).append(LineString(pontos))
                continue

            # ---- geometria de barra -----------------------------------
            if not self.cfg.layers.e_geometria_barra(layer):
                continue
            try:
                linha = LineString(pontos)
            except (ValueError, TypeError):
                continue
            if linha.length <= 0:
                continue
            if tol_simplif > 0:
                linha = linha.simplify(tol_simplif, preserve_topology=False)

            linetype = str(getattr(e.dxf, "linetype", "") or "")
            conteudo.geometrias.append(GeometriaDXF(
                handle=str(e.dxf.handle), geometria=linha,
                comprimento_desenho=linha.length,
                angulo=self._angulo_principal(linha),
                layer=layer, linetype=linetype, prancha=prancha,
                e_distribuicao=casa_padrao(linetype,
                                           self.cfg.layers.linetypes_distribuicao),
            ))

        conteudo.aneis_area = aneis_area
        conteudo.segmentos_area = segmentos_area
        # INSERTs da layer AREA podem nomear o trecho via atributo.
        conteudo.blocos_area = [
            e for e in entidades
            if e.dxftype() == "INSERT" and self.cfg.layers.e_area(e.dxf.layer)
        ]
        # Textos candidatos a nomear areas (inclui os ignorados: o rotulo da
        # area costuma estar numa layer de anotacao).
        conteudo.textos_para_nome = [
            t for t in (conteudo.textos + conteudo.textos_fora_filtro
                        + conteudo.textos_ignorados)
            if casa_padrao(t.layer, self.cfg.areas.layers_nome_area)
        ]

        self.log.info("  textos de armadura: %d | geometrias de barra: %d",
                      len(conteudo.textos), len(conteudo.geometrias))
        return conteudo

    # ------------------------------------------------------------------
    # Percurso do desenho
    # ------------------------------------------------------------------
    def _percorrer(self, doc) -> Iterator[DXFEntity]:
        """Gera as entidades do desenho, explodindo blocos ate a profundidade
        configurada. Blocos aninhados sao resolvidos em WCS pelo ezdxf."""
        espacos = [doc.modelspace()]
        if self.cfg.leitura.ler_paperspace:
            espacos += [doc.layouts.get(n) for n in doc.layout_names() if n != "Model"]

        for espaco in espacos:
            for e in espaco:
                yield from self._expandir(e, self.cfg.leitura.profundidade_blocos)

    def _expandir(self, e: DXFEntity, nivel: int) -> Iterator[DXFEntity]:
        if e.dxftype() != "INSERT":
            yield e
            return
        yield e   # o proprio INSERT interessa para ler atributos de AREA
        if nivel <= 0:
            return
        try:
            for filho in e.virtual_entities():
                yield from self._expandir(filho, nivel - 1)
        except Exception as exc:                      # bloco corrompido/proxy
            self.log.debug("bloco %s nao explodido: %s",
                           getattr(e.dxf, "name", "?"), exc)

    # ------------------------------------------------------------------
    # Extracao de texto
    # ------------------------------------------------------------------
    def _extrair_textos(self, e: DXFEntity) -> Iterator[tuple[str, float, float, float, float]]:
        """Devolve (texto, x, y, altura, rotacao) por linha do texto.

        MTEXT com varias linhas rende varias tuplas quando
        `agrupamento.quebrar_mtext` estiver ligado: no Eberick cada linha
        de um MTEXT empilhado e uma posicao diferente, nao um texto quebrado.
        """
        tipo = e.dxftype()
        try:
            if tipo == "MTEXT":
                conteudo = e.plain_text()
                altura = float(getattr(e.dxf, "char_height", 0) or 0)
                insert = e.dxf.insert
            else:
                conteudo = str(e.dxf.text)
                altura = float(getattr(e.dxf, "height", 0) or 0)
                # TEXT alinhado usa align_point em vez de insert.
                insert = e.dxf.insert
                alinhamento = getattr(e.dxf, "halign", 0)
                if alinhamento and e.dxf.hasattr("align_point"):
                    insert = e.dxf.align_point
            rot = float(getattr(e.dxf, "rotation", 0) or 0)
        except (AttributeError, ValueError, TypeError):
            return

        x, y = float(insert[0]), float(insert[1])
        if tipo == "MTEXT" and self.cfg.agrupamento.quebrar_mtext:
            linhas = [ln for ln in conteudo.splitlines() if ln.strip()]
            if not linhas:
                return
            # Cada linha desce uma altura; suficiente para o agrupamento
            # espacial distinguir posicoes empilhadas.
            for i, linha in enumerate(linhas):
                yield linha, x, y - i * (altura or 0), altura, rot
        else:
            yield conteudo.replace("\n", " "), x, y, altura, rot

    # ------------------------------------------------------------------
    # Geometria
    # ------------------------------------------------------------------
    def _pontos(self, e: DXFEntity, tol: float) -> list[tuple[float, float]]:
        """Achata qualquer entidade para uma lista de pontos 2D em WCS.

        `make_path` do ezdxf resolve LINE, LWPOLYLINE com bulge, POLYLINE,
        ARC, SPLINE e ELLIPSE com a mesma chamada.
        """
        distancia = tol if tol > 0 else 0.01
        try:
            caminho = make_path(e)
            pts = [(p.x, p.y) for p in caminho.flattening(distance=distancia)]
        except Exception:
            # Fallback para entidades que o make_path nao aceita.
            try:
                if e.dxftype() == "LINE":
                    pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
                elif e.dxftype() == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                elif e.dxftype() == "POLYLINE":
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                else:
                    return []
            except Exception:
                return []
        # Remove pontos repetidos consecutivos (o shapely nao gosta).
        limpos = [pts[0]] if pts else []
        for p in pts[1:]:
            if abs(p[0] - limpos[-1][0]) > 1e-9 or abs(p[1] - limpos[-1][1]) > 1e-9:
                limpos.append(p)
        return limpos

    def _esta_fechado(self, e: DXFEntity, pontos: list[tuple[float, float]]) -> bool:
        """Fechada pela flag do CAD, ou por coincidencia dos extremos."""
        if getattr(e.dxf, "flags", None) is not None:
            if e.dxftype() == "LWPOLYLINE" and bool(getattr(e, "closed", False)):
                return True
            if e.dxftype() == "POLYLINE" and bool(getattr(e, "is_closed", False)):
                return True
        if len(pontos) < 3:
            return False
        perimetro = sum(math.dist(pontos[i], pontos[i + 1]) for i in range(len(pontos) - 1))
        if perimetro <= 0:
            return False
        folga = math.dist(pontos[0], pontos[-1])
        return folga <= self.cfg.leitura.tolerancia_fechamento_rel * perimetro

    @staticmethod
    def _angulo_principal(linha: LineString) -> float:
        """Direcao do maior segmento, em graus 0-180.

        Usar o maior segmento (e nao o vetor inicio-fim) deixa o angulo
        correto mesmo em barras com dobras nas pontas.
        """
        coords = list(linha.coords)
        melhor, comp_max = 0.0, -1.0
        for a, b in zip(coords, coords[1:]):
            d = math.dist(a, b)
            if d > comp_max:
                comp_max = d
                melhor = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        return melhor % 180.0


class ConteudoPrancha:
    """Tudo que foi lido de uma prancha."""

    def __init__(self, prancha: str, total_entidades: int = 0) -> None:
        self.prancha = prancha
        self.total_entidades = total_entidades
        self.altura_mediana: float = 1.0
        self.textos: list[TextoDXF] = []
        self.textos_fora_filtro: list[TextoDXF] = []
        self.textos_ignorados: list[TextoDXF] = []
        self.textos_para_nome: list[TextoDXF] = []
        self.textos_tabela: list[TextoDXF] = []
        self.textos_distribuicao: list[TextoDXF] = []
        self.geometrias: list[GeometriaDXF] = []
        self.aneis_area: list[tuple[Polygon, str, bool, str]] = []
        self.segmentos_area: dict[str, list[LineString]] = {}
        self.blocos_area: list[DXFEntity] = []


# =============================================================================
# Montagem dos poligonos da layer AREA
# =============================================================================

def montar_areas(
    conteudo: ConteudoPrancha, cfg: Config, indice_inicial: int,
    e_armadura=None,
) -> tuple[list[AreaProjeto], list[Inconsistencia]]:
    """Transforma o que foi lido da layer AREA em poligonos nomeados.

    Duas origens sao aceitas:
      - polilinhas ja fechadas;
      - segmentos soltos (LINEs) que juntos formam um contorno fechado -
        o caso da prancha de exemplo, onde a AREA sao 4 LINEs separadas.

    `e_armadura(texto) -> bool` evita que uma posicao de armadura que por
    acaso caia dentro do poligono vire o nome do trecho.
    """
    log = obter_log()
    inconsistencias: list[Inconsistencia] = []
    candidatos: list[tuple[Polygon, str, bool, str]] = list(conteudo.aneis_area)

    # --- poligonizacao dos segmentos soltos, UMA LAYER POR VEZ --------
    for layer, segmentos in sorted(conteudo.segmentos_area.items()):
        if not cfg.areas.montar_de_segmentos:
            inconsistencias.append(Inconsistencia(
                TipoInconsistencia.AREA_NAO_FECHADA, Severidade.ERRO,
                f"{len(segmentos)} polilinha(s) aberta(s) na layer '{layer}' e "
                "areas.montar_de_segmentos esta desligado",
                prancha=conteudo.prancha, layer=layer))
            continue
        try:
            # COSTURA DOS EXTREMOS, antes de qualquer coisa.
            #
            # O polygonize exige que os nos coincidam EXATAMENTE. Num
            # retangulo desenhado no CAD os cantos costumam bater ate a
            # ultima casa decimal, mas nem sempre: ja apareceu um contorno
            # cujo canto tinha dois nos separados por 1e-13 - invisivel na
            # tela, suficiente para o anel nao fechar e o trecho inteiro
            # desaparecer do relatorio.
            #
            # `snap` junta vertices a menos da tolerancia. A tolerancia e
            # minuscula (fracao da altura do texto), entao costura ruido
            # numerico sem mascarar contorno realmente aberto.
            costurados = _costurar(segmentos, cfg.tol_costura_area)
            # unary_union faz o "noding": cruzamentos viram vertices, o que
            # permite ao polygonize fechar os aneis corretamente.
            montados = [g for g in polygonize(unary_union(costurados))
                        if g.area > 0]
            if montados and not list(polygonize(unary_union(segmentos))):
                log.info("  layer '%s': contorno so fechou apos costurar "
                         "extremos soltos (tolerancia %.2e)",
                         layer, cfg.tol_costura_area)
                inconsistencias.append(Inconsistencia(
                    TipoInconsistencia.AREA_COSTURADA, Severidade.INFO,
                    f"o contorno da layer '{layer}' tinha extremos que nao "
                    f"coincidiam exatamente e foi fechado automaticamente "
                    f"(tolerancia {cfg.tol_costura_area:.2e} unidades de "
                    f"desenho). O trecho existe no relatorio; se quiser "
                    f"eliminar o aviso, use o comando JUNTAR/JOIN no CAD",
                    prancha=conteudo.prancha, layer=layer))
        except Exception as exc:
            log.warning("  falha ao montar area da layer '%s': %s", layer, exc)
            montados = []

        for poli in montados:
            candidatos.append((poli, "", True, layer))

        if montados:
            log.info("  layer '%s': %d poligono(s) montado(s) de %d segmento(s)",
                     layer, len(montados), len(segmentos))
        else:
            inconsistencias.append(Inconsistencia(
                TipoInconsistencia.AREA_NAO_FECHADA, Severidade.ERRO,
                f"{len(segmentos)} entidade(s) na layer '{layer}' nao formam "
                "nenhum contorno fechado; este trecho NAO existira no "
                "relatorio e a armadura dele cai em SEM_AREA",
                prancha=conteudo.prancha, layer=layer))

    # --- filtro de area minima ----------------------------------------
    area_min = cfg.area_minima
    validos: list[tuple[Polygon, str, bool, str]] = []
    for poli, handle, montado, layer in candidatos:
        if poli.area < area_min:
            inconsistencias.append(Inconsistencia(
                TipoInconsistencia.AREA_DEGENERADA, Severidade.ALERTA,
                f"poligono de AREA com area {poli.area:.2f} < minimo "
                f"{area_min:.2f} (unidades de desenho ao quadrado); descartado",
                prancha=conteudo.prancha, layer=layer, handle=handle,
                x=poli.centroid.x, y=poli.centroid.y,
            ))
            continue
        validos.append((poli, handle, montado, layer))

    # Poligonos montados por polygonize podem incluir o contorno externo e
    # os "buracos" internos. Descarta quem contem outro por inteiro apenas
    # quando ha aninhamento real, para nao contar a mesma regiao duas vezes.
    validos.sort(key=lambda t: -t[0].area)

    # --- nomeacao ------------------------------------------------------
    areas: list[AreaProjeto] = []
    for i, (poli, handle, montado, layer) in enumerate(validos):
        nome, origem = _nomear(poli, conteudo, cfg, indice_inicial + i,
                               e_armadura, layer)
        areas.append(AreaProjeto(
            nome=nome, poligono=poli, prancha=conteudo.prancha,
            layer=layer,
            origem_nome=origem, handles=(handle,) if handle else (),
            montado_de_segmentos=montado,
        ))

    # --- sobreposicao --------------------------------------------------
    for i in range(len(areas)):
        for j in range(i + 1, len(areas)):
            a, b = areas[i].poligono, areas[j].poligono
            if not a.intersects(b):
                continue
            inter = a.intersection(b).area
            menor = min(a.area, b.area)
            if menor > 0 and inter / menor > cfg.areas.tolerancia_sobreposicao:
                inconsistencias.append(Inconsistencia(
                    TipoInconsistencia.AREA_SOBREPOSTA, Severidade.ERRO,
                    f"'{areas[i].nome}' e '{areas[j].nome}' se sobrepoem em "
                    f"{inter / menor * 100:.1f}% da menor; a armadura da regiao "
                    "comum e contada na primeira area, gerando subcontagem",
                    prancha=conteudo.prancha, layer=areas[i].layer,
                    x=a.intersection(b).centroid.x, y=a.intersection(b).centroid.y,
                ))
    return areas, inconsistencias


def _nomear(poli: Polygon, conteudo: ConteudoPrancha, cfg: Config,
            indice: int, e_armadura=None,
            layer: str = "") -> tuple[str, str]:
    """Descobre o nome do trecho seguindo a ordem de `areas.fonte_nome`."""
    for fonte in cfg.areas.fonte_nome:
        if fonte == "nome_layer":
            # Cada trecho na sua propria layer: o nome da layer E o nome
            # do trecho (TRECHO 01, TRECHO 02...). Nao vale para layer
            # generica - uma unica 'AREA' nomearia todos os trechos igual.
            nome = _nome_pela_layer(layer, cfg)
            if nome:
                return nome, "nome_layer"
        elif fonte == "atributo_bloco":
            for bloco in conteudo.blocos_area:
                try:
                    ins = bloco.dxf.insert
                    if not poli.contains(_ponto(ins[0], ins[1])):
                        continue
                    for attr in bloco.attribs:
                        valor = str(attr.dxf.text).strip()
                        if valor:
                            return valor, "atributo_bloco"
                except Exception:
                    continue
        elif fonte == "texto_interno":
            candidatos = [
                t for t in conteudo.textos_para_nome
                if t.conteudo.strip()
                # Nem posicao de armadura nem ruido (cota de dobra, escala)
                # nomeiam um trecho. Sem este filtro o rotulo viraria algo
                # como "20N6-Ø6.3c/18 C=300" ou "19".
                and not (e_armadura and e_armadura(t.conteudo))
                # Um rotulo de trecho nao e escrito menor que o texto comum
                # da prancha.
                and t.altura >= conteudo.altura_mediana
                and poli.contains(_ponto(t.x, t.y))
            ]
            if candidatos:
                # O rotulo do trecho costuma ser o maior texto de dentro.
                candidatos.sort(key=lambda t: -t.altura)
                return candidatos[0].conteudo.strip()[:60], "texto_interno"
        elif fonte == "sequencial":
            break
    return f"{cfg.areas.prefixo_sequencial}-{indice + 1:02d}", "sequencial"


def _costurar(segmentos: list[LineString], tol: float) -> list[LineString]:
    """Junta extremos que estao a menos de `tol` um do outro.

    Arredonda cada coordenada para uma grade de passo `tol`. Dois pontos
    separados por menos que isso caem na mesma celula e passam a ser o
    MESMO no - que e o que o polygonize precisa para fechar o anel.

    Arredondar (em vez de usar shapely.snap par a par) resolve tambem o
    caso de tres ou mais extremos proximos, e custa O(n) em vez de O(n^2).
    """
    if tol <= 0:
        return segmentos

    def grade(v: float) -> float:
        return round(v / tol) * tol

    costurados = []
    for seg in segmentos:
        pts = [(grade(x), grade(y)) for x, y in seg.coords]
        # o arredondamento pode colapsar pontos consecutivos
        limpos = [pts[0]]
        for p in pts[1:]:
            if p != limpos[-1]:
                limpos.append(p)
        if len(limpos) >= 2:
            costurados.append(LineString(limpos))
    return costurados


def _ponto(x: float, y: float):
    from shapely.geometry import Point
    return Point(x, y)


def _nome_pela_layer(layer: str, cfg: Config) -> str:
    """Nome do trecho a partir da layer, quando ela for especifica.

    Devolve string vazia quando a layer e generica demais para identificar
    um trecho (por exemplo uma unica layer "AREA" com varias regioes).
    """
    nome = (layer or "").strip()
    if not nome or normalizar_nome(nome) in _LAYERS_GENERICAS:
        return ""
    if cfg.areas.limpar_prefixo_layer:
        prefixo = re.escape(cfg.areas.prefixo_layer_trecho)
        sem_prefixo = re.sub(rf"^{prefixo}\s*[-_:]?\s*", "", nome,
                             flags=re.IGNORECASE).strip()
        nome = sem_prefixo or nome
    return nome[:60]
