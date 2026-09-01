"""
Classificacao das armaduras por AREA - a funcao central do programa.

Cada poligono da layer AREA delimita um trecho do projeto. Toda posicao de
armadura e atribuida a um trecho pelo teste ponto-em-poligono, usando
indice espacial STRtree.

CASOS LIMITE (documentados tambem no PREMISSAS.md):

  a) Barra inteiramente dentro de uma area
     -> vai toda para essa area. Sem ambiguidade.

  b) Barra CORTADA pelo contorno da area (parte dentro, parte fora)
     -> criterio `maior_parte` (PADRAO): a barra inteira vai para o trecho
        que contem O MAIOR COMPRIMENTO dela. Nenhuma barra e perdida: se
        encostar em algum trecho, e contada nele por inteiro. E o criterio
        de quem quer INCLUIR TUDO e fechar o projeto em 100%.
     -> criterio `centroide`: a barra inteira vai para a area que contem o
        PONTO MEDIO. Parece igual ao anterior, mas nao e: numa barra 80%
        dentro de A cujo ponto medio caia em B, o centroide manda tudo
        para B - o lado errado.
     -> criterio `fora_do_escopo`: a barra nao pertence integralmente a
        trecho nenhum, entao nao e contada em nenhum. Vai para a categoria
        FORA_DO_ESCOPO, sem gerar alerta. Uso: medicao conservadora, em
        que so conta o que esta inteiramente dentro do trecho.
     -> criterio `proporcional`: o peso e rateado pela fracao do
        comprimento dentro de cada area. Mais fiel fisicamente; exige que
        a barra tenha geometria associada (senao cai no centroide).

  c) Barra fora de qualquer area
     -> categoria SEM_AREA. Continua no RESUMO GERAL (o total geral nunca
        perde aco) e aparece em INCONSISTENCIAS para conferencia.

  d) Areas sobrepostas
     -> a armadura da regiao comum e contada na PRIMEIRA area (maior),
        gerando subcontagem na outra. A sobreposicao e sinalizada como
        inconsistencia na leitura (ver leitura.montar_areas).
"""
from __future__ import annotations

from typing import Optional

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from .config import Config
from .modelos import AreaProjeto


class ClassificadorAreas:
    """Indexa os poligonos e responde a que trecho cada armadura pertence."""

    def __init__(self, areas: list[AreaProjeto], cfg: Config) -> None:
        self.cfg = cfg
        # Ordem estavel e previsivel: da maior para a menor area. Assim, em
        # caso de sobreposicao, o resultado nao depende da ordem de leitura
        # do arquivo.
        self.areas = sorted(areas, key=lambda a: -a.poligono.area)
        self._tree = (STRtree([a.poligono for a in self.areas])
                      if self.areas else None)

    # ------------------------------------------------------------------
    def classificar(
        self, x: float, y: float, geometria: Optional[LineString] = None
    ) -> list[tuple[str, float]]:
        """Devolve [(nome_da_area, fracao)] com as fracoes somando 1.0.

        No criterio `centroide` a lista tem sempre um unico item.
        """
        if not self.areas:
            return [(self.cfg.areas.nome_sem_area, 1.0)]

        criterio = self.cfg.areas.criterio_divisa
        # Os dois criterios que olham a barra inteira precisam da geometria;
        # sem ela (texto sem barra associada) so resta o teste do ponto.
        if geometria is not None:
            if criterio == "maior_parte":
                return self._maior_parte(geometria, x, y)
            if criterio == "proporcional":
                return self._proporcional(geometria, x, y)
            if criterio == "fora_do_escopo":
                return self._fora_do_escopo(geometria, x, y)
        return self._centroide(x, y)

    # ------------------------------------------------------------------
    def _maior_parte(self, linha: LineString, x: float,
                     y: float) -> list[tuple[str, float]]:
        """A barra inteira vai para o trecho onde ela mais esta.

        Compara o COMPRIMENTO da barra dentro de cada poligono e escolhe o
        maior - nao o ponto medio. Numa barra que atravessa a divisa entre
        dois trechos, ganha o lado que fica com mais barra.

        Nenhuma barra e descartada: basta encostar em um trecho para ser
        contada nele por inteiro. So vai para SEM_AREA a barra que nao
        toca poligono nenhum.
        """
        total = linha.length
        if total <= 0:
            return self._centroide(x, y)

        melhor_nome: Optional[str] = None
        melhor_comp = 0.0
        # `self.areas` esta ordenado da maior para a menor area, entao um
        # empate exato resolve sempre do mesmo jeito.
        for i in sorted(int(k) for k in self._tree.query(linha)):
            try:
                comp = self.areas[i].poligono.intersection(linha).length
            except Exception:
                continue
            if comp > melhor_comp:
                melhor_comp = comp
                melhor_nome = self.areas[i].nome

        if melhor_nome is None or melhor_comp <= 0:
            # Nem encostou em trecho nenhum: aqui falta contorno mesmo.
            return [(self.cfg.areas.nome_sem_area, 1.0)]
        return [(melhor_nome, 1.0)]

    # ------------------------------------------------------------------
    def _fora_do_escopo(self, linha: LineString, x: float,
                        y: float) -> list[tuple[str, float]]:
        """Barra cortada pelo contorno nao entra no trecho.

        Tres desfechos possiveis:
          - barra INTEIRA dentro de uma area  -> conta naquela area;
          - barra CORTADA pelo contorno       -> FORA_DO_ESCOPO (sem alerta);
          - barra inteira fora de tudo        -> SEM_AREA.

        A varredura e feita em duas passadas de proposito: uma barra pode
        cortar o contorno de uma area e ainda assim estar inteira dentro de
        outra (areas aninhadas). O "inteira dentro" sempre tem prioridade.
        """
        total = linha.length
        if total <= 0:
            return self._centroide(x, y)

        eps = self.cfg.areas.tolerancia_corte
        candidatos = sorted(int(k) for k in self._tree.query(linha))
        cortada = False

        for i in candidatos:
            try:
                dentro = self.areas[i].poligono.intersection(linha).length
            except Exception:
                continue
            if dentro >= total * (1.0 - eps):
                return [(self.areas[i].nome, 1.0)]      # inteira dentro
            if dentro > total * eps:
                cortada = True                          # so encostou nao conta

        if cortada:
            return [(self.cfg.areas.nome_fora_escopo, 1.0)]
        return [(self.cfg.areas.nome_sem_area, 1.0)]

    # ------------------------------------------------------------------
    def _centroide(self, x: float, y: float) -> list[tuple[str, float]]:
        ponto = Point(x, y)
        # A consulta ao STRtree devolve candidatos pela envoltoria; o teste
        # exato de ponto-em-poligono e feito depois, so nos candidatos.
        for i in sorted(int(k) for k in self._tree.query(ponto)):
            if self.areas[i].poligono.covers(ponto):
                return [(self.areas[i].nome, 1.0)]
        return [(self.cfg.areas.nome_sem_area, 1.0)]

    # ------------------------------------------------------------------
    def _proporcional(self, linha: LineString, x: float,
                      y: float) -> list[tuple[str, float]]:
        """Rateia pelo comprimento da barra dentro de cada area."""
        total = linha.length
        if total <= 0:
            return self._centroide(x, y)

        fracoes: list[tuple[str, float]] = []
        acumulado = 0.0
        restante = linha

        for i in sorted(int(k) for k in self._tree.query(linha)):
            area = self.areas[i]
            if restante.is_empty:
                break
            try:
                dentro = restante.intersection(area.poligono)
            except Exception:
                continue
            comp = getattr(dentro, "length", 0.0)
            if comp <= 0:
                continue
            fracao = comp / total
            fracoes.append((area.nome, fracao))
            acumulado += fracao
            # Remove o trecho ja atribuido: evita contar duas vezes o
            # pedaco comum quando ha areas sobrepostas.
            try:
                restante = restante.difference(area.poligono)
            except Exception:
                pass

        sobra = 1.0 - acumulado
        if sobra > 1e-6:
            fracoes.append((self.cfg.areas.nome_sem_area, sobra))
        if not fracoes:
            return [(self.cfg.areas.nome_sem_area, 1.0)]

        # Normaliza para eliminar erro numerico acumulado: as fracoes
        # PRECISAM somar 1.0, senao o total geral nao fecha com a soma
        # das areas na aba VERIFICACAO.
        soma = sum(f for _, f in fracoes)
        if soma > 0 and abs(soma - 1.0) > 1e-9:
            fracoes = [(n, f / soma) for n, f in fracoes]
        return fracoes

    # ------------------------------------------------------------------
    @property
    def nomes(self) -> list[str]:
        return [a.nome for a in self.areas]


def desambiguar_nomes(areas: list[AreaProjeto],
                      vistos: dict[str, int] | None = None) -> None:
    """Garante nomes unicos de trecho, com UMA excecao importante.

    Regra geral: duas pranchas podem trazer 'AREA-01' cada uma, ou dois
    poligonos podem receber o mesmo texto interno. Nomes assim sao
    acidentais e precisam ser separados, senao trechos diferentes cairiam
    na mesma aba.

    EXCECAO - nome vindo da LAYER: ai o nome e deliberado, e layer com o
    mesmo nome e SEMPRE o mesmo trecho. Vale nos dois eixos:

      - entre pranchas: uma laje e desenhada em varias pranchas
        complementares (longitudinal inferior, transversal inferior,
        longitudinal superior, transversal superior) e a layer "TRECHO A"
        das quatro se refere a MESMA regiao da obra;

      - dentro da mesma prancha: um trecho pode ser desenhado como DOIS
        poligonos separados (uma regiao em L, ou partida por um vazio).
        Renomear o segundo para "TRECHO FT (2)" partiria o trecho em dois
        e tiraria metade dele de qualquer conta feita por nome.

    Por isso o nome vindo de layer nunca e alterado.
    """
    if vistos is None:
        vistos = {}
    for a in areas:
        base = a.nome.strip() or "AREA"
        if a.origem_nome == "nome_layer":
            a.nome = base
            continue
        if base not in vistos:
            vistos[base] = 1
            a.nome = base
        else:
            vistos[base] += 1
            a.nome = f"{base} ({vistos[base]})"
