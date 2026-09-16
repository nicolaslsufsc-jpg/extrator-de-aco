"""
Testes da tela (streamlit_app.py).

O que estes testes protegem, em uma frase: o resultado NAO pode sumir da
tela quando se clica em qualquer outra coisa. O Streamlit reexecuta o
arquivo inteiro a cada clique; com o resultado montado dentro do
`if st.button(...)`, bastava clicar em "Baixar planilha" para a tela
inteira se apagar - e era preciso processar tudo de novo.
"""
import shutil
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from tests.conftest import ARQUIVO_REFERENCIA, RAIZ

# O AppTest resolve caminho relativo contra ESTE arquivo, que mora em
# tests/. Sem o caminho absoluto ele procuraria tests/streamlit_app.py.
RAIZ_APP = str(RAIZ / "streamlit_app.py")
ESPERA = 300     # o pipeline real roda aqui; 3s (o padrao) nao basta


def _app():
    return AppTest.from_file(RAIZ_APP, default_timeout=ESPERA)


@pytest.fixture
def pasta_com_a_prancha(tmp_path):
    """Uma pasta de lote com a prancha de referencia dentro."""
    if not ARQUIVO_REFERENCIA.is_file():
        pytest.skip(f"{ARQUIVO_REFERENCIA.name} nao encontrado")
    destino = tmp_path / "pranchas"
    destino.mkdir()
    shutil.copy(ARQUIVO_REFERENCIA, destino / ARQUIVO_REFERENCIA.name)
    return destino


def _por_rotulo(widgets, trecho: str):
    """Acha o widget pelo rotulo, nunca pelo indice.

    O AppTest lista o corpo da pagina antes da barra lateral; mudar uma
    caixa de lugar renumeraria tudo e quebraria os testes por engano.
    """
    for w in widgets:
        if trecho.lower() in (w.label or "").lower():
            return w
    raise AssertionError(f"widget com rotulo contendo {trecho!r} nao encontrado")


def _campo_da_pasta(at):
    return _por_rotulo(at.text_input, "Caminho da pasta")


def _uma_caixa_da_lateral(at):
    return _por_rotulo(at.checkbox, "Separar por sentido")


def _processar(at, pasta):
    _campo_da_pasta(at).set_value(str(pasta)).run()
    at.button[0].click().run()
    return at


# =============================================================================
# Caminho digitado
# =============================================================================

def test_caminho_entre_aspas_e_aceito(pasta_com_a_prancha):
    """O "Copiar como caminho" do Windows entrega a pasta ENTRE ASPAS.
    Colado cru, a tela dizia "Pasta nao encontrada" para um caminho certo."""
    at = _app().run()
    _campo_da_pasta(at).set_value(f'"{pasta_com_a_prancha}"').run()
    assert not at.error, [e.value for e in at.error]
    assert any("prancha encontrada" in s.value for s in at.success)


def test_caminho_com_espaco_sobrando_e_aceito(pasta_com_a_prancha):
    at = _app().run()
    _campo_da_pasta(at).set_value(f"  {pasta_com_a_prancha}  ").run()
    assert not at.error, [e.value for e in at.error]


def test_pasta_sem_prancha_avisa_ANTES_de_processar(tmp_path):
    """Descobrir que a pasta esta vazia so depois de apertar Processar e
    fazer o usuario esperar por um erro que dava para dizer na hora."""
    vazia = tmp_path / "sem_nada_dentro"
    vazia.mkdir()
    at = _app().run()
    _campo_da_pasta(at).set_value(str(vazia)).run()
    assert at.error, "deveria avisar que a pasta nao tem DXF"
    assert at.button[0].disabled, "Processar tem de ficar bloqueado"


def test_pasta_inexistente_nao_libera_o_botao(tmp_path):
    at = _app().run()
    _campo_da_pasta(at).set_value(str(tmp_path / "nao_existe")).run()
    assert at.error
    assert at.button[0].disabled


# =============================================================================
# O resultado tem de sobreviver ao proximo clique
# =============================================================================

@pytest.mark.slow
def test_resultado_sobrevive_a_um_novo_clique(pasta_com_a_prancha):
    """O bug principal: clicar no download (ou em qualquer widget) apagava
    indicadores, tabelas e o proprio botao de baixar."""
    at = _processar(_app().run(), pasta_com_a_prancha)
    assert at.session_state["execucao"]["ok"]
    assert at.metric, "os indicadores tinham de estar na tela"
    antes = len(at.metric)

    # Qualquer interacao reexecuta o arquivo inteiro. Aqui, uma caixa da
    # lateral - e o efeito e o mesmo do botao de download.
    caixa = _uma_caixa_da_lateral(at)
    caixa.set_value(not caixa.value).run()

    assert at.metric, "o resultado sumiu da tela depois de um clique"
    assert len(at.metric) == antes
    assert at.download_button, "o botao de baixar sumiu"


@pytest.mark.slow
def test_planilha_continua_disponivel_para_baixar_apos_um_clique(
        pasta_com_a_prancha):
    """Os bytes do .xlsx ficam no session_state: o arquivo temporario ja
    foi apagado, entao ler do disco na hora de desenhar nao serviria."""
    at = _processar(_app().run(), pasta_com_a_prancha)
    caixa = _uma_caixa_da_lateral(at)
    caixa.set_value(not caixa.value).run()
    dados = at.session_state["execucao"]["xlsx"]
    assert dados[:2] == b"PK", "deveria ser um .xlsx valido"
    assert len(dados) > 5000


# =============================================================================
# Erro
# =============================================================================

@pytest.mark.slow
def test_erro_no_processamento_fica_na_tela(pasta_com_a_prancha, monkeypatch):
    """Antes: st.error seguido de st.stop(). A mensagem aparecia e sumia no
    clique seguinte, sem deixar rastro de onde tinha falhado."""
    import extrator.pipeline

    def explodir(*a, **k):
        raise RuntimeError("falha proposital do teste")

    monkeypatch.setattr(extrator.pipeline, "processar", explodir)

    at = _processar(_app().run(), pasta_com_a_prancha)
    exe = at.session_state["execucao"]
    assert not exe["ok"]
    assert "falha proposital do teste" in exe["erro"]
    # O traceback e guardado para o usuario poder mandar junto.
    assert "RuntimeError" in exe["traceback"]
    assert at.error, "a falha tem de aparecer na tela"

    # E continua la depois de mexer em outra coisa.
    caixa = _uma_caixa_da_lateral(at)
    caixa.set_value(not caixa.value).run()
    assert at.error, "a mensagem de erro sumiu no clique seguinte"


@pytest.mark.slow
def test_erro_nao_deixa_pasta_temporaria_para_tras(pasta_com_a_prancha,
                                                   monkeypatch):
    """A limpeza estava so no caminho feliz: cada tentativa que falhava
    deixava uma pasta de arquivos enviados no disco."""
    import tempfile

    import extrator.pipeline

    monkeypatch.setattr(extrator.pipeline, "processar",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))

    raiz = Path(tempfile.gettempdir())
    antes = {p for p in raiz.glob("extrator_aco_*")}
    _processar(_app().run(), pasta_com_a_prancha)
    depois = {p for p in raiz.glob("extrator_aco_*")}
    assert depois == antes, f"sobrou lixo no disco: {depois - antes}"
