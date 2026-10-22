"""
Malha declarada em tabela, distribuida entre os trechos.

A malha (tela de Ø5.0 sobre o EPS, por exemplo) nao e desenhada barra a
barra na prancha: ela aparece so como uma TABELA a parte, com a quantidade
total de barras do pavimento inteiro. Entao nao ha o que ler no desenho -
o total e declarado, e o que falta e repartir esse total entre os trechos.

O criterio e o PESO DE ARMADURA de cada trecho: um trecho que concentra
30% do aco da obra leva 30% da malha. E a melhor proporcao disponivel sem
medir area de laje, porque a armadura ja acompanha o tamanho e a carga de
cada regiao.

Arredondamento SEMPRE para cima, trecho a trecho: nao se compra fracao de
barra, e faltar barra na obra custa mais do que sobrar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Config
from .log_config import obter_log


@dataclass(slots=True)
class LinhaMalha:
    """Quanto da malha cabe a um trecho."""
    trecho: str
    peso_armadura_kg: float      # o que o trecho tem de armadura desenhada
    fracao: float                # a parte dele no total (0 a 1)
    barras: int                  # ja com o acrescimo e arredondado para cima
    peso_kg: float
    ja_comprado: bool = False    # entra na conta, mas nao na compra


@dataclass(slots=True)
class ResultadoMalha:
    """A distribuicao inteira, pronta para virar aba de planilha."""
    linhas: list[LinhaMalha] = field(default_factory=list)
    descricao: str = ""
    bitola_mm: float = 0.0
    categoria: str = ""
    comprimento_unitario_cm: float = 0.0
    peso_por_barra_kg: float = 0.0
    barras_tabela: int = 0           # o que a tabela da prancha declara
    acrescimo_percentual: float = 0.0

    @property
    def barras_a_comprar(self) -> int:
        return sum(l.barras for l in self.linhas if not l.ja_comprado)

    @property
    def peso_a_comprar_kg(self) -> float:
        return sum(l.peso_kg for l in self.linhas if not l.ja_comprado)

    @property
    def barras_total(self) -> int:
        return sum(l.barras for l in self.linhas)

    @property
    def peso_total_kg(self) -> float:
        return sum(l.peso_kg for l in self.linhas)


# =============================================================================
def peso_por_barra(cfg: Config) -> float:
    """Peso de uma barra da malha, em kg.

    Vale o que a tabela da prancha declara (`peso_por_barra_kg`), porque e
    esse o numero que o projetista conferiu. So quando ele nao for dado e
    que o peso sai da bitola x comprimento.
    """
    m = cfg.malha
    if m.peso_por_barra_kg:
        return float(m.peso_por_barra_kg)
    linear = cfg.calculo.peso_linear_de(m.bitola_mm) or 0.0
    return linear * (m.comprimento_unitario_cm / 100.0)


def distribuir(pesos_por_trecho: dict[str, float], cfg: Config) -> ResultadoMalha:
    """Reparte as barras da malha entre os trechos, pelo peso de cada um.

    `pesos_por_trecho` ja deve vir SEM as categorias que nao sao trecho
    (SEM_AREA, FORA_DO_ESCOPO): malha se compra para a laje que existe, nao
    para armadura que ficou sem dono.
    """
    m = cfg.malha
    resultado = ResultadoMalha(
        descricao=m.descricao, bitola_mm=m.bitola_mm, categoria=m.categoria,
        comprimento_unitario_cm=m.comprimento_unitario_cm,
        peso_por_barra_kg=peso_por_barra(cfg),
        barras_tabela=m.quantidade_barras,
        acrescimo_percentual=m.acrescimo_percentual,
    )
    total = sum(p for p in pesos_por_trecho.values() if p > 0)
    if not total or not m.quantidade_barras:
        return resultado

    # O acrescimo entra nas BARRAS, antes de repartir: assim cada trecho
    # ja recebe a sua folga, em vez de uma sobra solta no fim.
    com_folga = m.quantidade_barras * (1.0 + m.acrescimo_percentual)
    ja_comprados = {t.strip().upper() for t in m.trechos_ja_comprados}

    for trecho, peso in sorted(pesos_por_trecho.items(),
                               key=lambda kv: -kv[1]):
        if peso <= 0:
            continue
        fracao = peso / total
        barras = math.ceil(com_folga * fracao)
        resultado.linhas.append(LinhaMalha(
            trecho=trecho,
            peso_armadura_kg=peso,
            fracao=fracao,
            barras=barras,
            peso_kg=barras * resultado.peso_por_barra_kg,
            ja_comprado=trecho.strip().upper() in ja_comprados,
        ))

    log = obter_log()
    log.info("  malha: %d barra(s) da tabela + %.0f%% = %d distribuida(s) "
             "entre %d trecho(s)", m.quantidade_barras,
             m.acrescimo_percentual * 100, resultado.barras_total,
             len(resultado.linhas))
    if ja_comprados:
        log.info("  malha: %d barra(s) a COMPRAR (fora %s)",
                 resultado.barras_a_comprar,
                 ", ".join(sorted(ja_comprados)))
    return resultado


def pesos_dos_trechos(df, cfg: Config) -> dict[str, float]:
    """Peso de armadura por trecho, deixando de fora o que nao e trecho."""
    if df.empty:
        return {}
    fora = {cfg.areas.nome_sem_area, cfg.areas.nome_fora_escopo}
    base = "Peso (kg)"      # liquido: a proporcao nao deve depender da perda
    soma = df[~df["Area"].isin(fora)].groupby("Area")[base].sum()
    return {str(k): float(v) for k, v in soma.items() if v > 0}
