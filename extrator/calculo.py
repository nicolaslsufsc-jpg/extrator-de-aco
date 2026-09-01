"""
Calculo do quantitativo.

Formulas (todas por posicao):
    comprimento_total (m) = quantidade x comprimento_unitario (cm) / 100
    peso_liquido    (kg)  = comprimento_total (m) x peso_linear (kg/m)
    peso_com_perda  (kg)  = peso_liquido x (1 + perda)

Peso linear pela NBR 7480, tabela embutida e editavel no config.yaml.
Os valores foram conferidos contra a tabela de resumo do proprio DWG de
exemplo (diferenca menor que 0,2%, vinda do arredondamento do Eberick).

No criterio `proporcional` de divisa entre areas, a posicao aparece uma vez
por area com `fracao_area` < 1, e TODAS as grandezas ja saem rateadas.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from .config import Config
from .modelos import (Inconsistencia, PosicaoArmadura, Severidade,
                      TipoInconsistencia)


def calcular(pos: PosicaoArmadura, cfg: Config) -> Optional[Inconsistencia]:
    """Preenche categoria, pesos e comprimentos de uma posicao.

    Devolve uma inconsistencia quando a bitola nao tem peso linear
    cadastrado - nesse caso o peso fica zero e o aco NAO entra no total,
    o que precisa aparecer no relatorio.
    """
    pos.categoria = cfg.calculo.categoria_de(pos.bitola_mm, pos.posicao)

    peso_linear = cfg.calculo.peso_linear_de(pos.bitola_mm)
    if peso_linear is None:
        pos.peso_linear_kg_m = 0.0
        pos.comprimento_total_m = (pos.quantidade * pos.fracao_area
                                   * pos.comprimento_unit_cm / 100.0)
        pos.peso_liquido_kg = 0.0
        pos.peso_com_perda_kg = 0.0
        return Inconsistencia(
            TipoInconsistencia.SEM_PESO_LINEAR, Severidade.ERRO,
            f"bitola {pos.bitola_mm} mm nao tem peso linear em "
            f"calculo.peso_linear; o peso desta posicao ficou ZERO e nao "
            f"entrou no total",
            prancha=pos.prancha, layer=pos.layer_texto, handle=pos.handle_texto,
            texto=pos.texto_origem, x=pos.x_texto, y=pos.y_texto,
        )

    pos.peso_linear_kg_m = peso_linear
    pos.comprimento_total_m = (pos.quantidade * pos.fracao_area
                               * pos.comprimento_unit_cm / 100.0)
    pos.peso_liquido_kg = pos.comprimento_total_m * peso_linear
    pos.peso_com_perda_kg = pos.peso_liquido_kg * (1.0 + cfg.calculo.perda_percentual)
    return None


def conferir_distribuicao(
    pos: PosicaoArmadura, extensao_desenho: Optional[float],
    escala_cm_por_unidade: Optional[float], cfg: Config
) -> Optional[Inconsistencia]:
    """Confere a quantidade do texto contra a linha tracejada de distribuicao.

    No padrao Eberick vale  quantidade = ceil(extensao / espacamento).
    Conferido na prancha de exemplo em 8 posicoes (N1: 2375/15 -> 159 ✓,
    N5: 350/10 -> 35 ✓, N7: 375/10 -> 38 ✓).

    Esta e uma CONFERENCIA, nao uma correcao: o texto continua mandando no
    quantitativo, a menos que `calculo.recalcular_quantidade` seja ligado.
    """
    if (extensao_desenho is None or not pos.espacamento_cm
            or pos.espacamento_cm <= 0 or not escala_cm_por_unidade):
        return None

    extensao_cm = extensao_desenho * escala_cm_por_unidade
    qtd_calc = math.ceil(extensao_cm / pos.espacamento_cm)
    if qtd_calc <= 0:
        return None

    divergencia = abs(qtd_calc - pos.quantidade) / max(pos.quantidade, 1)
    if divergencia <= cfg.calculo.tolerancia_divergencia_qtd:
        return None

    if cfg.calculo.recalcular_quantidade:
        antiga = pos.quantidade
        pos.quantidade = qtd_calc
        calcular(pos, cfg)
        return Inconsistencia(
            TipoInconsistencia.DIVERGENCIA_QUANTIDADE, Severidade.ALERTA,
            f"quantidade recalculada pela distribuicao: {antiga} -> {qtd_calc} "
            f"(extensao {extensao_cm:.0f} cm / esp. {pos.espacamento_cm:.0f} cm)",
            prancha=pos.prancha, layer=pos.layer_texto, handle=pos.handle_texto,
            texto=pos.texto_origem, x=pos.x_texto, y=pos.y_texto,
        )

    return Inconsistencia(
        TipoInconsistencia.DIVERGENCIA_QUANTIDADE, Severidade.ALERTA,
        f"texto diz {pos.quantidade} barras; a linha de distribuicao indica "
        f"{qtd_calc} (extensao {extensao_cm:.0f} cm / esp. "
        f"{pos.espacamento_cm:.0f} cm) - divergencia de {divergencia * 100:.0f}%",
        prancha=pos.prancha, layer=pos.layer_texto, handle=pos.handle_texto,
        texto=pos.texto_origem, x=pos.x_texto, y=pos.y_texto,
    )


# =============================================================================
# Tabelas
# =============================================================================

COLUNAS_BASE = [
    "Posicao", "Bitola (mm)", "Categoria", "Quantidade",
    "Dobra 1 (cm)", "Reta (cm)", "Dobra 2 (cm)",
    "Comprimento unitario (cm)", "Comprimento total (m)",
    "Peso (kg)", "Peso com perda (kg)",
]


def montar_dataframe(posicoes: list[PosicaoArmadura], cfg: Config) -> pd.DataFrame:
    """Converte as posicoes em DataFrame - a base de todas as abas."""
    if not posicoes:
        return pd.DataFrame(
            columns=COLUNAS_BASE + ["Area", "Sentido", "Prancha"])

    linhas = []
    for p in posicoes:
        linhas.append({
            "Posicao": f"N{p.posicao}",
            "Bitola (mm)": p.bitola_mm,
            "Categoria": p.categoria,
            "Quantidade": p.quantidade * p.fracao_area,
            "Dobra 1 (cm)": p.dobra1_cm,
            "Reta (cm)": p.reta_cm,
            "Dobra 2 (cm)": p.dobra2_cm,
            "Comprimento unitario (cm)": p.comprimento_unit_cm,
            "Comprimento total (m)": p.comprimento_total_m,
            "Peso (kg)": p.peso_liquido_kg,
            "Peso com perda (kg)": p.peso_com_perda_kg,
            "Area": p.area,
            "Sentido": p.sentido or "",
            "Prancha": p.prancha,
            # --- diagnostico (opcional na saida) ---
            "Qtd desenho": p.quantidade_desenho,
            "Origem da qtd": p.origem_quantidade,
            "Texto no desenho": p.texto_origem,
            "Espacamento (cm)": p.espacamento_cm,
            "Comp. variavel": "SIM" if p.comprimento_variavel else "",
            "Fracao na area": p.fracao_area,
            "Score associacao": p.score_associacao,
            "Handle texto": p.handle_texto,
            "Handle barra": p.handle_barra or "",
            "Layer": p.layer_texto,
            "X": p.x_repr,
            "Y": p.y_repr,
        })
    return pd.DataFrame(linhas)


def agrupar_por_posicao(df: pd.DataFrame) -> pd.DataFrame:
    """Consolida a tabela no formato do resumo de aco.

    Uma mesma posicao (N5, por exemplo) aparece varias vezes no desenho,
    uma por trecho de distribuicao. O resumo mostra uma linha por
    (posicao, bitola, comprimento unitario), como faz o Eberick.
    """
    if df.empty:
        return df
    # As colunas de dobra entram na chave: sao constantes por posicao e
    # precisam sobreviver ao agrupamento (e uma lista de corte e dobra).
    chaves = ["Posicao", "Bitola (mm)", "Categoria",
              "Dobra 1 (cm)", "Reta (cm)", "Dobra 2 (cm)",
              "Comprimento unitario (cm)"]
    agregado = (
        df.groupby(chaves, as_index=False, sort=False, dropna=False)
          .agg({
              "Quantidade": "sum",
              "Comprimento total (m)": "sum",
              "Peso (kg)": "sum",
              "Peso com perda (kg)": "sum",
          })
    )
    # Ordena por bitola e depois pelo numero da posicao (N2 antes de N10).
    agregado["_ordem"] = agregado["Posicao"].str.extract(r"(\d+)").astype(float)
    agregado = agregado.sort_values(
        ["Bitola (mm)", "_ordem", "Posicao"]
    ).drop(columns="_ordem").reset_index(drop=True)
    return agregado


def resumo_por_bitola(df: pd.DataFrame) -> pd.DataFrame:
    """Subtotais por bitola - as linhas de subtotal do relatorio."""
    if df.empty:
        return pd.DataFrame(columns=["Bitola (mm)", "Categoria", "Quantidade",
                                     "Comprimento total (m)", "Peso (kg)",
                                     "Peso com perda (kg)"])
    return (
        df.groupby(["Bitola (mm)", "Categoria"], as_index=False)
          .agg({
              "Quantidade": "sum",
              "Comprimento total (m)": "sum",
              "Peso (kg)": "sum",
              "Peso com perda (kg)": "sum",
          })
          .sort_values("Bitola (mm)")
          .reset_index(drop=True)
    )


def resumo_por_sentido(df: pd.DataFrame) -> pd.DataFrame:
    """Peso por trecho e sentido - base das secoes internas da aba do trecho."""
    if df.empty:
        return pd.DataFrame(columns=["Area", "Sentido", "Comprimento total (m)",
                                     "Peso (kg)", "Peso com perda (kg)"])
    return (
        df.groupby(["Area", "Sentido"], as_index=False)
          .agg({
              "Comprimento total (m)": "sum",
              "Peso (kg)": "sum",
              "Peso com perda (kg)": "sum",
          })
          .sort_values(["Area", "Sentido"])
          .reset_index(drop=True)
    )


def eficacia_por_bitola(df: pd.DataFrame, nomes_fora: list[str],
                        coluna: str) -> pd.DataFrame:
    """Compara a tabela mestre com o que foi atribuido a trechos nomeados.

    Eficacia = peso dentro de trechos / peso total extraido. Mede se todos
    os trechos da obra foram desenhados: com o projeto todo delimitado, o
    valor tende a 100%.
    """
    if df.empty:
        return pd.DataFrame(columns=["Bitola (mm)", "Tabela mestre (kg)",
                                     "Total nos trechos (kg)", "Fora (kg)",
                                     "Eficacia"])
    dentro = df[~df["Area"].isin(nomes_fora)]
    mestre = df.groupby("Bitola (mm)", as_index=False)[coluna].sum()
    mestre = mestre.rename(columns={coluna: "Tabela mestre (kg)"})
    trechos = dentro.groupby("Bitola (mm)", as_index=False)[coluna].sum()
    trechos = trechos.rename(columns={coluna: "Total nos trechos (kg)"})

    tabela = mestre.merge(trechos, on="Bitola (mm)", how="left")
    tabela["Total nos trechos (kg)"] = tabela["Total nos trechos (kg)"].fillna(0.0)
    tabela["Fora (kg)"] = (tabela["Tabela mestre (kg)"]
                           - tabela["Total nos trechos (kg)"])
    tabela["Eficacia"] = tabela.apply(
        lambda r: (r["Total nos trechos (kg)"] / r["Tabela mestre (kg)"]
                   if r["Tabela mestre (kg)"] else 0.0), axis=1)
    return tabela.sort_values("Bitola (mm)").reset_index(drop=True)


def resumo_por_area(df: pd.DataFrame) -> pd.DataFrame:
    """Peso por area e bitola - base da aba VERIFICACAO."""
    if df.empty:
        return pd.DataFrame(columns=["Area", "Bitola (mm)", "Peso (kg)",
                                     "Peso com perda (kg)"])
    return (
        df.groupby(["Area", "Bitola (mm)"], as_index=False)
          .agg({
              "Comprimento total (m)": "sum",
              "Peso (kg)": "sum",
              "Peso com perda (kg)": "sum",
          })
          .sort_values(["Area", "Bitola (mm)"])
          .reset_index(drop=True)
    )


def estimar_escala(posicoes: list[PosicaoArmadura]) -> Optional[float]:
    """Estima quantos centimetros reais vale uma unidade de desenho.

    Compara o comprimento DESENHADO da barra com o comprimento DECLARADO no
    texto (C=). Serve so para diagnostico e para a conferencia da linha de
    distribuicao - nenhum peso e calculado a partir da geometria, porque a
    prancha pode misturar escalas (a de exemplo tem 1:50 e 1:25 na mesma
    folha).
    """
    razoes = []
    for p in posicoes:
        if p.geometria_barra is None or p.comprimento_variavel:
            continue
        comp_desenho = getattr(p.geometria_barra, "length", 0.0)
        if comp_desenho > 0 and p.comprimento_unit_cm > 0:
            razoes.append(p.comprimento_unit_cm / comp_desenho)
    if len(razoes) < 5:
        return None
    razoes.sort()
    return razoes[len(razoes) // 2]      # mediana: imune a barras com dobra
