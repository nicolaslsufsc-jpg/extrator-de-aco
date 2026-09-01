"""Fixtures compartilhadas: carrega o config.yaml real do projeto."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from extrator.config import carregar_config          # noqa: E402
from extrator.parser_texto import ParserArmadura     # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    """Config real do projeto - os testes validam a configuracao de producao."""
    return carregar_config(RAIZ / "config.yaml")


@pytest.fixture(autouse=True)
def _restaurar_cfg(cfg):
    """Devolve o config ao estado original depois de cada teste.

    O `cfg` e de sessao (carregar o YAML a cada teste seria desperdicio),
    mas varios testes trocam criterio de divisa, perda e categorias. Sem
    esta restauracao a suite ficaria dependente da ordem de execucao - e
    um teste passaria ou falharia conforme quem rodou antes.
    """
    guardado = {
        "criterio": cfg.areas.criterio_divisa,
        "perda": cfg.calculo.perda_percentual,
        "projeto": cfg.projeto,
        "altura": cfg.altura_referencia,
        "por_posicao": dict(cfg.calculo.categoria_por_posicao),
        "abas_por_area": cfg.saida.abas_por_area,
        "por_sentido": cfg.saida.agrupar_por_sentido,
        "modo_limpo": cfg.saida.modo_limpo,
        "modo_enxuto": cfg.saida.modo_enxuto,
        "fonte_qtd": cfg.calculo.fonte_quantidade,
        "limpar_prefixo": cfg.areas.limpar_prefixo_layer,
        # test_trechos aponta as layers para o DXF sintetico; sem restaurar,
        # os testes da prancha real que rodassem depois nao achariam nada.
        "texto_armadura": list(cfg.layers.texto_armadura),
        "geometria_barra": list(cfg.layers.geometria_barra),
        "area": list(cfg.layers.area),
    }
    yield
    cfg.areas.criterio_divisa = guardado["criterio"]
    cfg.calculo.perda_percentual = guardado["perda"]
    cfg.projeto = guardado["projeto"]
    cfg.altura_referencia = guardado["altura"]
    cfg.calculo.categoria_por_posicao.clear()
    cfg.calculo.categoria_por_posicao.update(guardado["por_posicao"])
    cfg.saida.abas_por_area = guardado["abas_por_area"]
    cfg.saida.agrupar_por_sentido = guardado["por_sentido"]
    cfg.saida.modo_limpo = guardado["modo_limpo"]
    cfg.saida.modo_enxuto = guardado["modo_enxuto"]
    cfg.calculo.fonte_quantidade = guardado["fonte_qtd"]
    cfg.areas.limpar_prefixo_layer = guardado["limpar_prefixo"]
    cfg.layers.texto_armadura = guardado["texto_armadura"]
    cfg.layers.geometria_barra = guardado["geometria_barra"]
    cfg.layers.area = guardado["area"]


@pytest.fixture(scope="session")
def parser(cfg):
    return ParserArmadura(cfg)


# ---------------------------------------------------------------------------
# O ARQUIVO DE REFERENCIA
# ---------------------------------------------------------------------------
# Todo teste que roda sobre um desenho de verdade usa ESTE arquivo, e so
# ele. Calibrar o programa em varias pranchas diferentes foi o que fez a
# leitura andar de lado: um ajuste que melhorava uma piorava outra sem
# ninguem perceber. Uma referencia unica torna qualquer regressao visivel.
# O caminho de sempre, no PC do autor. Se ele nao existir (outro PC, uma
# maquina Linux), procuramos O MESMO desenho dentro do proprio repositorio:
# continua sendo um unico arquivo de referencia, so que achado em outro
# lugar. Sem isso os testes de prancha real ficam silenciosamente pulados.
_PADRAO = Path("C:/Users/nicol/OneDrive/Desktop/SEM NADA.dxf")
ARQUIVO_REFERENCIA = _PADRAO if _PADRAO.is_file() else RAIZ / "SEM NADA.dxf"


@pytest.fixture(scope="session")
def dxf_referencia():
    """O desenho de referencia; os testes sao pulados se ele faltar."""
    if not ARQUIVO_REFERENCIA.is_file():
        pytest.skip(f"{ARQUIVO_REFERENCIA.name} nao encontrado")
    return ARQUIVO_REFERENCIA
