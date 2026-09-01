"""
Testes da quantidade recuperada pela extensao da distribuicao.

Uma armadura escrita "N3-Ø8c/10 C=300" nao diz quantas barras sao. Lida
ao pe da letra vira 1 barra - subcontagem de 10 a 25 vezes. A quantidade
esta na extensao da distribuicao, desenhada como numero solto ao lado.
"""
import pytest

from extrator.distribuicao import coletar_extensoes, recuperar_quantidades
from extrator.modelos import PosicaoArmadura, ResultadoProcessamento, TextoDXF


def _pos(posicao="3", esp=10.0, explicita=False, x=0.0, y=0.0, comp=300.0):
    return PosicaoArmadura(
        id="x", prancha="P", posicao=posicao, quantidade=1, bitola_mm=8.0,
        comprimento_unit_cm=comp, espacamento_cm=esp,
        texto_origem=f"N{posicao}-Ø8c/{esp:g} C={comp:g}",
        quantidade_explicita=explicita, x_texto=x, y_texto=y)


def _rotulo(x, y, valor, layer="ARR_L_I_IG_DIST"):
    return TextoDXF(handle="H", conteudo=str(valor), conteudo_bruto=str(valor),
                    x=x, y=y, altura=0.133, rotacao=0.0, layer=layer,
                    prancha="P")


@pytest.fixture(autouse=True)
def _calibra(cfg):
    cfg.calibrar(0.2)          # raio de associacao = 12 x 0.2 = 2.4


# =============================================================================
def test_quantidade_vem_de_extensao_dividida_pelo_espacamento(cfg):
    """200 cm de extensao com espacamento 10 -> 20 barras."""
    p = _pos(esp=10.0, x=0.0, y=0.0)
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(0.5, 0.0, 200.0)], cfg, "P", res)
    assert p.quantidade == 20
    assert p.extensao_distribuicao_cm == 200
    assert p.origem_quantidade == "distribuicao"


@pytest.mark.parametrize("extensao,esp,esperado", [
    (2375, 15, 159),   # conferido na prancha real: a tabela diz 159
    (350, 10, 35),     # a tabela diz 35
    (375, 10, 38),     # a tabela diz 38 (arredonda para cima)
    (275, 11, 25),     # a tabela diz 25
    (100, 10, 10),
])
def test_conta_confere_com_a_tabela_do_projeto(cfg, extensao, esp, esperado):
    p = _pos(esp=esp)
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(0.5, 0.0, float(extensao))], cfg, "P", res)
    assert p.quantidade == esperado


def test_quantidade_escrita_no_texto_manda(cfg):
    """"N264-1Ø10 C=790" tem o numero de barras; nao se mexe nele."""
    p = _pos(esp=10.0, explicita=True)
    p.quantidade = 1
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(0.5, 0.0, 500.0)], cfg, "P", res)
    assert p.quantidade == 1
    assert p.origem_quantidade != "distribuicao"


def test_barra_sem_espacamento_nao_e_tocada(cfg):
    p = _pos(esp=10.0)
    p.espacamento_cm = None
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(0.5, 0.0, 500.0)], cfg, "P", res)
    assert p.quantidade == 1


def test_sem_rotulo_no_raio_continua_1_mas_avisa(cfg):
    """Subcontagem silenciosa e o pior desfecho: tem de virar alerta."""
    p = _pos(esp=10.0, x=0.0, y=0.0)
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(999.0, 999.0, 200.0)], cfg, "P", res)
    assert p.quantidade == 1
    assert "DISTRIBUICAO_SEM_EXTENSAO" in [i.tipo.name for i in res.inconsistencias]


def test_nenhum_rotulo_no_desenho_avisa(cfg):
    p = _pos(esp=10.0)
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [], cfg, "P", res)
    assert p.quantidade == 1
    assert "DISTRIBUICAO_SEM_EXTENSAO" in [i.tipo.name for i in res.inconsistencias]


def test_dois_rotulos_equidistantes_viram_alerta(cfg):
    """Onde a escolha pode ter errado de barra, o programa avisa."""
    p = _pos(esp=10.0, x=0.0, y=0.0)
    res = ResultadoProcessamento()
    recuperar_quantidades([p], [(0.5, 0.0, 200.0), (0.0, 0.52, 100.0)],
                          cfg, "P", res)
    assert p.quantidade == 20          # adotou o mais proximo
    assert "DISTRIBUICAO_AMBIGUA" in [i.tipo.name for i in res.inconsistencias]


def test_pode_ser_desligado(cfg):
    cfg.calculo.recuperar_quantidade_distribuicao = False
    try:
        p = _pos(esp=10.0)
        res = ResultadoProcessamento()
        recuperar_quantidades([p], [(0.5, 0.0, 200.0)], cfg, "P", res)
        assert p.quantidade == 1
    finally:
        cfg.calculo.recuperar_quantidade_distribuicao = True


# =============================================================================
def test_coletar_so_pega_numero_puro_na_layer_certa(cfg):
    textos = [
        _rotulo(0, 0, "200"),                                  # vale
        _rotulo(1, 0, "150.5"),                                # vale
        _rotulo(2, 0, "N3-Ø8 C=300"),                          # nao e numero
        _rotulo(3, 0, "200", layer="ARR_LONG_INF_TXT"),        # layer errada
        _rotulo(4, 0, "0"),                                    # zero nao vale
    ]
    achados = coletar_extensoes(textos, cfg)
    assert [v for _, _, v in achados] == [200.0, 150.5]


# =============================================================================
@pytest.mark.slow
def test_recorte_real_recupera_as_quantidades(cfg, tmp_path, dxf_referencia):
    """Ponta a ponta no arquivo do usuario: as tres barras com c/ e sem
    quantidade passam a contar 20, 10 e 25 barras."""
    from extrator.log_config import configurar_log
    from extrator.pipeline import processar

    configurar_log(cfg.log, tmp_path)
    res = processar(dxf_referencia, cfg)
    por_pos = {p.posicao: p for p in res.posicoes}

    assert por_pos["3"].quantidade == 20     # extensao 200 / c/10
    assert por_pos["6"].quantidade == 10     # extensao 100 / c/10
    assert por_pos["13"].quantidade == 25    # extensao 250 / c/10
    # as que trazem o numero no texto continuam intactas
    assert por_pos["264"].quantidade == 1
    assert por_pos["31"].quantidade == 1
