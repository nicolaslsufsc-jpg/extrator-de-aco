"""
Associacao texto <-> barra.

Cada texto de armadura pertence a uma barra desenhada. A ligacao e feita
por proximidade combinada com alinhamento angular: no padrao Eberick o
texto e escrito paralelo a barra que descreve.

Performance: o indice espacial STRtree do shapely resolve a busca dos
candidatos em O(log n). Com 8.500 entidades a varredura O(n^2) faria
~36 milhoes de comparacoes; aqui sao algumas dezenas por texto.

Dentro de um grupo de textos empilhados a atribuicao e EXCLUSIVA (guloso
pelo melhor score): tres textos no mesmo ponto ocupam tres barras
diferentes, nao a mesma barra tres vezes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from shapely.geometry import Point
from shapely.strtree import STRtree

from .agrupamento import GrupoTextos
from .config import Config
from .modelos import GeometriaDXF, TextoDXF


@dataclass(slots=True)
class Associacao:
    """Resultado da associacao de um texto."""
    indice_texto: int
    indice_barra: Optional[int]
    score: Optional[float]
    distancia: Optional[float]
    duvidosa: bool


class AssociadorGeometrico:
    """Indexa as barras uma vez e responde as consultas de todos os textos."""

    def __init__(self, geometrias: list[GeometriaDXF], cfg: Config) -> None:
        self.cfg = cfg
        self.raio = cfg.raio_associacao
        comp_min = cfg.comprimento_min_barra

        # Linhas curtas demais sao dobras soltas, marcas de distribuicao ou
        # ruido - nunca o corpo de uma barra. Filtrar aqui melhora a
        # qualidade da associacao e reduz o tamanho do indice.
        self.barras: list[GeometriaDXF] = [
            g for g in geometrias
            if not g.e_distribuicao and g.comprimento_desenho >= comp_min
        ]
        self._tree = STRtree([g.geometria for g in self.barras]) if self.barras else None

    # ------------------------------------------------------------------
    def _candidatos(self, x: float, y: float) -> list[int]:
        """Indices das barras cuja envoltoria alcanca o raio de busca."""
        if self._tree is None:
            return []
        janela = Point(x, y).buffer(self.raio, quad_segs=4)
        return [int(i) for i in self._tree.query(janela)]

    def _score(self, texto: TextoDXF, barra: GeometriaDXF,
               distancia: float) -> float:
        """Score composto; quanto MENOR, melhor.

        Distancia normalizada pelo raio de busca + desalinhamento angular
        normalizado pelo angulo maximo aceitavel.
        """
        c = self.cfg.associacao
        s_dist = min(distancia / self.raio, 1.0) if self.raio > 0 else 1.0

        # Diferenca angular em 0-90: texto a 90 da barra e o pior caso.
        dif = abs((texto.rotacao % 180.0) - barra.angulo)
        dif = min(dif, 180.0 - dif)
        s_ang = min(dif / c.angulo_max_graus, 1.0)

        soma_pesos = c.peso_distancia + c.peso_angulo
        if soma_pesos <= 0:
            return s_dist
        return (c.peso_distancia * s_dist + c.peso_angulo * s_ang) / soma_pesos

    # ------------------------------------------------------------------
    def associar_grupo(self, grupo: GrupoTextos,
                       textos: list[TextoDXF]) -> list[Associacao]:
        """Associa todos os textos de um grupo, sem repetir barra.

        Monta os pares (texto, barra) candidatos, ordena pelo score e vai
        fixando o melhor par ainda disponivel. E o casamento guloso: nao e
        o otimo global, mas e estavel, previsivel e barato - e o otimo
        (algoritmo hungaro) nao se justifica para grupos de 2 a 4 textos.
        """
        c = self.cfg.associacao
        pares: list[tuple[float, float, int, int]] = []

        for idx in grupo.indices:
            t = textos[idx]
            ponto = Point(t.x, t.y)
            cands = self._candidatos(t.x, t.y)
            if len(cands) > c.max_candidatos:
                # Mantem so os mais proximos quando ha excesso de candidatos.
                cands.sort(key=lambda i: self.barras[i].geometria.distance(ponto))
                cands = cands[:c.max_candidatos]
            for i in cands:
                d = self.barras[i].geometria.distance(ponto)
                if d > self.raio:
                    continue
                pares.append((self._score(t, self.barras[i], d), d, idx, i))

        pares.sort(key=lambda p: p[0])
        texto_feito: set[int] = set()
        barra_usada: set[int] = set()
        resultado: dict[int, Associacao] = {}

        for score, dist, idx_t, idx_b in pares:
            if idx_t in texto_feito or idx_b in barra_usada:
                continue
            texto_feito.add(idx_t)
            barra_usada.add(idx_b)
            resultado[idx_t] = Associacao(
                indice_texto=idx_t, indice_barra=idx_b, score=score,
                distancia=dist, duvidosa=score > c.score_suspeito,
            )

        # Textos do grupo que ficaram sem barra (menos barras que textos,
        # ou nenhuma barra no raio).
        for idx in grupo.indices:
            if idx not in resultado:
                resultado[idx] = Associacao(idx, None, None, None, False)

        return [resultado[i] for i in grupo.indices]


def ponto_representativo(barra: Optional[GeometriaDXF],
                         texto: TextoDXF) -> tuple[float, float]:
    """Ponto usado no teste ponto-em-poligono.

    Preferencia pelo centroide da barra: e ele que representa onde o aco
    esta, e nao onde a legenda foi escrita. Sem barra associada, cai no
    ponto de insercao do texto.
    """
    if barra is not None:
        try:
            # `interpolate(0.5, normalized=True)` devolve um ponto SOBRE a
            # linha, enquanto o centroide de uma barra em L pode cair fora.
            p = barra.geometria.interpolate(0.5, normalized=True)
            return float(p.x), float(p.y)
        except Exception:
            pass
    return texto.x, texto.y


def extensao_distribuicao(barra: Optional[GeometriaDXF],
                          geometrias: list[GeometriaDXF],
                          cfg: Config) -> Optional[float]:
    """Comprimento da linha tracejada de distribuicao mais proxima da barra.

    Usado apenas para conferir a quantidade declarada no texto; nunca para
    alterar o quantitativo sem que `calculo.recalcular_quantidade` peca.
    Devolve o valor em unidades de desenho.
    """
    if barra is None:
        return None
    tracejadas = [g for g in geometrias if g.e_distribuicao]
    if not tracejadas:
        return None
    centro = barra.geometria.interpolate(0.5, normalized=True)
    melhor, menor = None, math.inf
    for g in tracejadas:
        d = g.geometria.distance(centro)
        if d < menor:
            menor, melhor = d, g
    if melhor is None or menor > cfg.raio_associacao:
        return None
    return melhor.comprimento_desenho
