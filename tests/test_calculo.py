"""Testes do calculo de peso, perda, categoria e agregacoes."""
import pytest

from extrator.calculo import (agrupar_por_posicao, calcular, montar_dataframe,
                              resumo_por_area, resumo_por_bitola)
from extrator.modelos import PosicaoArmadura


def _pos(**kw) -> PosicaoArmadura:
    base = dict(id="x", prancha="P1", posicao="1", quantidade=10,
                bitola_mm=10.0, comprimento_unit_cm=400.0, espacamento_cm=15.0,
                texto_origem="10N1-Ø10c/15 C=400", area="AREA-01")
    base.update(kw)
    return PosicaoArmadura(**base)


# =============================================================================
def test_comprimento_total_converte_cm_para_metro(cfg):
    p = _pos(quantidade=10, comprimento_unit_cm=400.0)
    calcular(p, cfg)
    assert p.comprimento_total_m == pytest.approx(40.0)   # 10 x 4,00 m


def test_peso_usa_a_tabela_nbr_7480(cfg):
    p = _pos(quantidade=10, comprimento_unit_cm=400.0, bitola_mm=10.0)
    calcular(p, cfg)
    assert p.peso_linear_kg_m == pytest.approx(0.617)
    assert p.peso_liquido_kg == pytest.approx(40.0 * 0.617)


def test_perda_aparece_em_coluna_separada_e_nao_altera_o_liquido(cfg):
    p = _pos()
    calcular(p, cfg)
    esperado = p.peso_liquido_kg * (1 + cfg.calculo.perda_percentual)
    assert p.peso_com_perda_kg == pytest.approx(esperado)
    assert p.peso_com_perda_kg > p.peso_liquido_kg


@pytest.mark.parametrize("bitola,categoria", [
    (5.0, "CA-60"), (6.0, "CA-60"),
    (6.3, "CA-50"), (8.0, "CA-50"), (10.0, "CA-50"), (12.5, "CA-50"),
    (16.0, "CA-50"), (20.0, "CA-50"), (25.0, "CA-50"), (32.0, "CA-50"),
])
def test_categoria_inferida_pela_bitola(cfg, bitola, categoria):
    p = _pos(bitola_mm=bitola)
    calcular(p, cfg)
    assert p.categoria == categoria


def test_categoria_pode_ser_sobrescrita_por_posicao(cfg):
    cfg.calculo.categoria_por_posicao["999"] = "CA-25"
    try:
        p = _pos(posicao="999", bitola_mm=10.0)
        calcular(p, cfg)
        assert p.categoria == "CA-25"
    finally:
        cfg.calculo.categoria_por_posicao.pop("999")


def test_bitola_sem_peso_linear_zera_o_peso_e_reporta(cfg):
    """Um peso silenciosamente errado seria pior que um peso zero + alerta."""
    p = _pos(bitola_mm=7.7)
    inc = calcular(p, cfg)
    assert inc is not None and inc.tipo.name == "SEM_PESO_LINEAR"
    assert p.peso_liquido_kg == 0.0


def test_fracao_de_area_rateia_todas_as_grandezas(cfg):
    """Criterio proporcional: metade da barra em cada area."""
    inteira = _pos(fracao_area=1.0)
    metade = _pos(fracao_area=0.5)
    calcular(inteira, cfg)
    calcular(metade, cfg)
    assert metade.comprimento_total_m == pytest.approx(inteira.comprimento_total_m / 2)
    assert metade.peso_liquido_kg == pytest.approx(inteira.peso_liquido_kg / 2)
    assert metade.peso_com_perda_kg == pytest.approx(inteira.peso_com_perda_kg / 2)


def test_soma_das_fracoes_reproduz_a_posicao_inteira(cfg):
    """Garantia central da aba VERIFICACAO: rateio nao cria nem perde aco."""
    inteira = _pos(fracao_area=1.0)
    calcular(inteira, cfg)
    partes = [_pos(fracao_area=f, area=a)
              for f, a in ((0.3, "A"), (0.45, "B"), (0.25, "SEM_AREA"))]
    for p in partes:
        calcular(p, cfg)
    assert sum(p.peso_liquido_kg for p in partes) == pytest.approx(
        inteira.peso_liquido_kg)


# =============================================================================
def test_agrupar_por_posicao_soma_repeticoes_da_mesma_posicao(cfg):
    """A mesma posicao aparece varias vezes no desenho (uma por distribuicao)."""
    posicoes = [_pos(posicao="5", quantidade=20),
                _pos(posicao="5", quantidade=35),
                _pos(posicao="7", quantidade=10)]
    for p in posicoes:
        calcular(p, cfg)
    ag = agrupar_por_posicao(montar_dataframe(posicoes, cfg))
    linha_n5 = ag[ag["Posicao"] == "N5"]
    assert len(linha_n5) == 1
    assert linha_n5["Quantidade"].iloc[0] == 55


def test_resumo_por_bitola_e_por_area_batem_com_o_total(cfg):
    posicoes = [
        _pos(bitola_mm=10.0, area="AREA-01"),
        _pos(bitola_mm=12.5, area="AREA-01"),
        _pos(bitola_mm=10.0, area="SEM_AREA"),
    ]
    for p in posicoes:
        calcular(p, cfg)
    df = montar_dataframe(posicoes, cfg)
    total = df["Peso (kg)"].sum()
    assert resumo_por_bitola(df)["Peso (kg)"].sum() == pytest.approx(total)
    assert resumo_por_area(df)["Peso (kg)"].sum() == pytest.approx(total)


def test_dataframe_vazio_nao_quebra(cfg):
    df = montar_dataframe([], cfg)
    assert df.empty
    assert agrupar_por_posicao(df).empty
