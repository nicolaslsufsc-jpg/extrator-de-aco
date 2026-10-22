"""
Testes da malha declarada em tabela.

A malha nao e desenhada barra a barra: a prancha so traz a tabela com o
total do pavimento. O que o programa faz e REPARTIR esse total entre os
trechos, pelo peso de armadura de cada um.
"""
import pytest

from extrator.malha import distribuir, peso_por_barra, pesos_dos_trechos

# Os numeros da obra real, para o teste nao virar aritmetica abstrata.
PESOS = {"TRECHO A": 15753.5, "TRECHO B": 14467.1,
         "TRECHO D": 18610.3, "TRECHO E": 15062.0}


@pytest.fixture
def cfg_malha(cfg):
    cfg.malha.ativar = True
    cfg.malha.quantidade_barras = 3188
    cfg.malha.peso_por_barra_kg = 1.8
    cfg.malha.acrescimo_percentual = 0.05
    cfg.malha.trechos_ja_comprados = []
    return cfg


def test_peso_declarado_na_tabela_vence_o_calculado(cfg_malha):
    """1.8 kg e o que o projetista conferiu; o calculo pela bitola daria
    1.85 (0.154 kg/m x 12 m). Vale o declarado."""
    assert peso_por_barra(cfg_malha) == 1.8
    cfg_malha.malha.peso_por_barra_kg = None
    assert peso_por_barra(cfg_malha) == pytest.approx(0.154 * 12, rel=1e-9)


def test_reparticao_segue_o_peso_de_armadura(cfg_malha):
    r = distribuir(PESOS, cfg_malha)
    por_trecho = {l.trecho: l for l in r.linhas}
    # O trecho com mais aco leva mais malha, na mesma ordem.
    assert (sorted(PESOS, key=PESOS.get, reverse=True)
            == [l.trecho for l in r.linhas])
    # A fracao e o peso do trecho sobre o total.
    total = sum(PESOS.values())
    for nome, peso in PESOS.items():
        assert por_trecho[nome].fracao == pytest.approx(peso / total)


def test_acrescimo_entra_nas_barras(cfg_malha):
    """5% de folga, somada ANTES de repartir, para cada trecho receber a
    sua parte dela em vez de sobrar um resto solto no fim."""
    cfg_malha.malha.acrescimo_percentual = 0.0
    sem = distribuir(PESOS, cfg_malha).barras_total
    cfg_malha.malha.acrescimo_percentual = 0.05
    com = distribuir(PESOS, cfg_malha).barras_total
    assert com > sem
    assert com == pytest.approx(sem * 1.05, rel=0.01)


def test_arredonda_sempre_para_CIMA(cfg_malha):
    """Nao se compra fracao de barra, e faltar na obra custa mais que
    sobrar. Por isso a soma pode passar do total da tabela."""
    r = distribuir(PESOS, cfg_malha)
    alvo = cfg_malha.malha.quantidade_barras * 1.05
    assert r.barras_total >= alvo
    # Passar, mas pouco: no maximo uma barra por trecho.
    assert r.barras_total - alvo < len(r.linhas)
    for l in r.linhas:
        assert l.barras == int(l.barras), "barra nao pode ser fracionada"


def test_peso_bate_com_as_barras(cfg_malha):
    r = distribuir(PESOS, cfg_malha)
    for l in r.linhas:
        assert l.peso_kg == pytest.approx(l.barras * 1.8)
    assert r.peso_total_kg == pytest.approx(r.barras_total * 1.8)


def test_trecho_ja_comprado_sai_da_compra_mas_fica_na_tabela(cfg_malha):
    """O trecho D ja foi comprado (errado): a parte dele continua
    calculada - e o que prova quanto foi - mas nao entra no que comprar."""
    cfg_malha.malha.trechos_ja_comprados = ["TRECHO D"]
    r = distribuir(PESOS, cfg_malha)

    d = next(l for l in r.linhas if l.trecho == "TRECHO D")
    assert d.ja_comprado
    assert d.barras > 0, "a parte dele tem de continuar na tabela"
    assert r.barras_a_comprar == r.barras_total - d.barras
    assert r.peso_a_comprar_kg == pytest.approx(r.peso_total_kg - d.peso_kg)


def test_trecho_ja_comprado_nao_muda_a_parte_dos_outros(cfg_malha):
    """Tirar o D da COMPRA nao pode inchar os outros: a parte de cada um
    continua sendo a sua. Senao estariamos comprando aco a mais."""
    antes = {l.trecho: l.barras for l in distribuir(PESOS, cfg_malha).linhas}
    cfg_malha.malha.trechos_ja_comprados = ["TRECHO D"]
    depois = {l.trecho: l.barras for l in distribuir(PESOS, cfg_malha).linhas}
    assert antes == depois


def test_sem_trecho_nenhum_nao_inventa_malha(cfg_malha):
    assert distribuir({}, cfg_malha).linhas == []


def test_sem_barras_na_tabela_nao_gera_nada(cfg_malha):
    cfg_malha.malha.quantidade_barras = 0
    assert distribuir(PESOS, cfg_malha).linhas == []


def test_pesos_dos_trechos_ignora_o_que_nao_e_trecho(cfg):
    """Malha se compra para a laje que existe, nao para armadura que
    ficou sem dono."""
    import pandas as pd

    df = pd.DataFrame([
        {"Area": "TRECHO A", "Peso (kg)": 100.0},
        {"Area": "TRECHO B", "Peso (kg)": 50.0},
        {"Area": cfg.areas.nome_sem_area, "Peso (kg)": 999.0},
        {"Area": cfg.areas.nome_fora_escopo, "Peso (kg)": 888.0},
    ])
    assert pesos_dos_trechos(df, cfg) == {"TRECHO A": 100.0, "TRECHO B": 50.0}
