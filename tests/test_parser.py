"""
Testes do parser de texto de armadura.

Cobrem os formatos do enunciado, os formatos reais encontrados na prancha
de exemplo do Eberick, e - o mais importante - a garantia de que texto nao
interpretado nunca some em silencio.
"""
import pytest


# =============================================================================
# Formatos do enunciado
# =============================================================================

def test_barra_distribuida_formato_manual(parser):
    """25 N1 Ø10 C/15 C=420 -> qtd 25, pos 1, Ø10, esp 15, comp 420."""
    r = parser.interpretar("25 N1 Ø10 C/15 C=420")
    assert len(r.posicoes) == 1
    p = r.posicoes[0]
    assert p.quantidade == 25
    assert p.posicao == "1"
    assert p.bitola_mm == 10.0
    assert p.espacamento_cm == 15.0
    assert p.comprimento_cm == 420.0


def test_barra_unica_sem_quantidade_e_sem_espacamento(parser):
    """N7 Ø12,5 C=340 -> assume 1 unidade e nenhum espacamento."""
    r = parser.interpretar("N7 Ø12,5 C=340")
    assert len(r.posicoes) == 1
    p = r.posicoes[0]
    assert p.quantidade == 1
    assert p.posicao == "7"
    assert p.bitola_mm == 12.5          # virgula decimal
    assert p.espacamento_cm is None
    assert p.comprimento_cm == 340.0


@pytest.mark.parametrize("texto", [
    "25 N1 Ø10 C/15 C=420",
    "25 N1 ø10 c/15 c=420",
    "25 N1 φ10 C/15 COMP=420",
    "25 N1 #10 C/15 C=420",
    "25 N1 Ø10 esp.15 C=420",
    "25 N1 Ø10 @15 C=420",
])
def test_variacoes_de_simbolo_e_separador(parser, texto):
    """Ø, ø, φ, #, C/, c/, esp., @, C=, c=, COMP= devem todos funcionar."""
    r = parser.interpretar(texto)
    assert len(r.posicoes) == 1, f"nao interpretou: {texto!r}"
    p = r.posicoes[0]
    assert (p.quantidade, p.bitola_mm, p.espacamento_cm, p.comprimento_cm) == \
           (25, 10.0, 15.0, 420.0)


@pytest.mark.parametrize("texto,esperado", [
    ("N7 Ø12,5 C=340", 12.5),
    ("N7 Ø12.5 C=340", 12.5),
])
def test_separador_decimal_virgula_ou_ponto(parser, texto, esperado):
    assert parser.interpretar(texto).posicoes[0].bitola_mm == esperado


def test_ordem_invertida_comprimento_antes_do_espacamento(parser):
    r = parser.interpretar("25 N1 Ø10 C=420 C/15")
    p = r.posicoes[0]
    assert p.comprimento_cm == 420.0 and p.espacamento_cm == 15.0


# =============================================================================
# Formatos reais da prancha de exemplo (Eberick / AltoQi)
# =============================================================================

def test_codigo_de_controle_autocad_por_cento_c(parser):
    """%%c e como o Eberick grava o Ø no DXF; sem a troca nada casaria."""
    r = parser.interpretar("159N1-%%c10c/15 C=880")
    p = r.posicoes[0]
    assert p.quantidade == 159
    assert p.posicao == "1"
    assert p.bitola_mm == 10.0
    assert p.espacamento_cm == 15.0
    assert p.comprimento_cm == 880.0


def test_codigo_de_controle_maiusculo(parser):
    p = parser.interpretar("25N3-%%C6.3c/11 C=111").posicoes[0]
    assert (p.quantidade, p.bitola_mm, p.espacamento_cm, p.comprimento_cm) == \
           (25, 6.3, 11.0, 111.0)


def test_sem_espacamento_com_quantidade(parser):
    p = parser.interpretar("1N100-%%c12.5 C=1160").posicoes[0]
    assert p.quantidade == 1 and p.espacamento_cm is None
    assert p.comprimento_cm == 1160.0


def test_posicao_com_sufixo_alfabetico(parser):
    p = parser.interpretar("11N215B-%%C16 C=100").posicoes[0]
    assert p.posicao == "215B" and p.bitola_mm == 16.0


def test_comprimento_variavel_usa_a_media_e_alerta(parser):
    """C=880-900 e barra de comprimento variavel: media + alerta obrigatorio."""
    r = parser.interpretar("159N1-%%c10c/15 C=880-900")
    p = r.posicoes[0]
    assert p.comprimento_variavel is True
    assert p.comprimento_min_cm == 880.0
    assert p.comprimento_max_cm == 900.0
    assert p.comprimento_cm == 890.0
    tipos = [pr.tipo.name for pr in r.problemas]
    assert "COMPRIMENTO_VARIAVEL" in tipos, "estimativa precisa ser sinalizada"


def test_duas_posicoes_no_mesmo_texto(parser):
    """O Eberick junta duas posicoes com '+' num unico TEXT."""
    r = parser.interpretar("2N50-%%c10 C=300+2N51-%%c10 C=250")
    assert len(r.posicoes) == 2
    assert [p.posicao for p in r.posicoes] == ["50", "51"]
    assert [p.comprimento_cm for p in r.posicoes] == [300.0, 250.0]


def test_detalhe_tipico_posicao_antes_da_quantidade(parser):
    p = parser.interpretar("N1-8Ø16.0 C=180").posicoes[0]
    assert p.posicao == "1" and p.quantidade == 8
    assert p.bitola_mm == 16.0 and p.comprimento_cm == 180.0


# =============================================================================
# Ruido e falhas - nada pode sumir em silencio
# =============================================================================

@pytest.mark.parametrize("texto", [
    "", "   ", "19", "2375", "ESC. 1:50", "PLANTA", "Laje L1", "---",
])
def test_ruido_conhecido_e_ignorado_sem_virar_erro(parser, texto):
    r = parser.interpretar(texto)
    assert r.ignorado is True
    assert r.posicoes == [] and r.problemas == []


@pytest.mark.parametrize("texto", [
    "N1 sem bitola nenhuma",
    "ARMADURA POSITIVA DA LAJE",
    "25 N1 Ø10 C/15",              # falta o comprimento
])
def test_texto_desconhecido_vira_problema_e_nao_e_descartado(parser, texto):
    r = parser.interpretar(texto)
    assert r.posicoes == []
    assert r.ignorado is False
    assert r.problemas, "texto nao interpretado precisa gerar inconsistencia"
    assert r.problemas[0].tipo.name == "TEXTO_NAO_INTERPRETADO"


def test_bitola_fora_da_nbr_entra_no_calculo_mas_alerta(parser):
    """Descartar seria pior: a posicao entra e o problema e reportado."""
    r = parser.interpretar("10 N1 Ø9.7 C=200")
    assert len(r.posicoes) == 1
    assert [p.tipo.name for p in r.problemas] == ["BITOLA_INVALIDA"]


def test_bitola_quase_certa_e_arredondada_para_a_nbr(parser):
    """12.4 esta dentro de parser.tolerancia_bitola (0.3) de 12.5."""
    r = parser.interpretar("10 N1 Ø12.4 C=200")
    assert r.posicoes[0].bitola_mm == 12.5
    assert not r.problemas


def test_comprimento_absurdo_gera_alerta(parser):
    r = parser.interpretar("10 N1 Ø10 C=99999")
    assert len(r.posicoes) == 1
    assert "COMPRIMENTO_SUSPEITO" in [p.tipo.name for p in r.problemas]


# =============================================================================
# Rede de seguranca de layer
# =============================================================================

def test_parece_armadura_detecta_posicao_em_layer_errada(parser):
    assert parser.parece_armadura("25N3-%%C6.3c/11 C=111") is True
    assert parser.parece_armadura("ESC. 1:50") is False
    assert parser.parece_armadura("19") is False


def test_ruido_nunca_vira_nome_de_area(parser):
    """Sem isto, o rotulo do trecho viraria '19' ou uma posicao de armadura."""
    assert parser.nao_serve_como_rotulo("19") is True
    assert parser.nao_serve_como_rotulo("159N1-%%c10c/15 C=880") is True
    assert parser.nao_serve_como_rotulo("REGIAO A") is False


# =============================================================================
# Normalizacao
# =============================================================================

def test_normalizacao_troca_codigos_e_limpa_espacos(parser):
    assert parser.normalizar("25  N1  %%c10") == "25 N1 Ø10"
    assert parser.normalizar("%%%") == "%"


def test_unidades_do_config_sao_respeitadas(cfg, parser):
    """O parser converte para cm/mm conforme unidades do config.yaml."""
    assert cfg.unidades.comprimento_texto == "cm"
    assert parser.interpretar("1 N1 Ø10 C=420").posicoes[0].comprimento_cm == 420.0
