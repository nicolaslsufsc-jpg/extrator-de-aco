"""
Interface grafica do Extrator de Aco.

Executar:
    python -m streamlit run streamlit_app.py

A interface e apenas uma casca em volta de `extrator.pipeline.processar`:
toda a regra de negocio e a mesma da linha de comando.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from extrator.calculo import (montar_dataframe, resumo_por_area,
                             resumo_por_bitola, resumo_por_sentido)
from extrator.config import Config, carregar_config
from extrator.conversor import localizar_oda
from extrator.exportacao import Exportador
from extrator.log_config import configurar_log
from extrator.pipeline import processar

RAIZ = Path(__file__).resolve().parent

st.set_page_config(page_title="Extrator de Aco", page_icon="⚙", layout="wide")
st.title("Extrator de Aço")
st.caption("Levantamento de armadura a partir de plantas DWG/DXF, "
           "separado pelos trechos delimitados no desenho")


# =============================================================================
# Barra lateral - configuracao
# =============================================================================
with st.sidebar:
    st.header("Configuração")
    caminho_cfg = st.text_input("config.yaml", str(RAIZ / "config.yaml"))

# A carga do config fica FORA do bloco da lateral de proposito: se ela
# falhar, o erro precisa aparecer no corpo da pagina. Reportado so na
# lateral, com ela recolhida, a tela parece simplesmente vazia.
try:
    cfg = carregar_config(caminho_cfg)
except Exception as exc:
    st.error(f"**Não foi possível ler o config.yaml**\n\n```\n{exc}\n```")
    if "extra_forbidden" in str(exc):
        st.warning(
            "Esse erro quase sempre significa que o servidor está rodando "
            "com uma versão antiga do código: o `config.yaml` tem uma opção "
            "que o programa carregado na memória ainda não conhece. "
            "**Pare o Streamlit (Ctrl+C) e inicie de novo** — o Python só "
            "recarrega os módulos importados ao reiniciar o processo."
        )
    with st.sidebar:
        st.error("config.yaml inválido — veja o detalhe na página.")
    st.stop()

with st.sidebar:
    nome_projeto = st.text_input(
        "Nome do projeto", "",
        help="Vira o prefixo das abas do Excel. Em branco, usa o nome do "
             "arquivo (ou da pasta, quando for um lote).")

    st.subheader("Cálculo")
    cfg.calculo.perda_percentual = st.slider(
        "Perda (%)", 0, 30, int(cfg.calculo.perda_percentual * 100)) / 100

    # A lista vem do proprio schema do config: assim, um criterio novo
    # aparece aqui sozinho e nunca falta uma opcao (foi o que quebrou a
    # tela quando "maior_parte" entrou).
    opcoes = list(
        Config.model_fields["areas"].annotation
        .model_fields["criterio_divisa"].annotation.__args__)
    atual = cfg.areas.criterio_divisa
    cfg.areas.criterio_divisa = st.radio(
        "Barra que cruza a divisa entre trechos",
        opcoes,
        index=opcoes.index(atual) if atual in opcoes else 0,
        help="maior_parte: a barra inteira vai para o trecho onde ela mais "
             "está (maior comprimento). Inclui tudo — nada se perde.\n"
             "centroide: vai para o trecho que contém o ponto médio.\n"
             "proporcional: rateia pelo comprimento dentro de cada trecho.\n"
             "fora_do_escopo: não conta em trecho nenhum.",
    )

    cfg.saida.abas_por_area = st.checkbox("Gerar uma aba por trecho", True)
    cfg.saida.agrupar_por_sentido = st.checkbox(
        "Separar por sentido dentro do trecho", True,
        help="Cada aba de trecho ganha uma seção por direção da armadura "
             "(X horizontal, Y vertical), com subtotais próprios.")
    # Um radio, e nao dois checkboxes: "limpa" e "enxuta" sao graus da
    # mesma coisa, e marcar os dois nao significaria nada.
    MODOS = {
        "Enxuta (recomendada)":
            "Uma aba por trecho com a lista de corte e dobra, mais a aba "
            "CONFERÊNCIA (cada barra desenhada consta na tabela do "
            "projeto?). Nada mais. Problemas viram uma observação no topo "
            "da CONFERÊNCIA.",
        "Limpa":
            "As abas de trecho, o RESUMO GERAL e a COMPARAÇÃO FINAL. Sem "
            "o detalhamento linha-a-linha e sem as abas VERIFICAÇÃO e "
            "INCONSISTÊNCIAS.",
        "Completa":
            "Tudo: RESUMO GERAL, abas de trecho, COMPARAÇÃO FINAL, "
            "VERIFICAÇÃO, INCONSISTÊNCIAS e o detalhamento linha-a-linha.",
    }
    modo = st.radio("Planilha", list(MODOS),
                    help="\n\n".join(f"**{k}** — {v}" for k, v in MODOS.items()))
    cfg.saida.modo_enxuto = modo.startswith("Enxuta")
    cfg.saida.modo_limpo = modo == "Limpa"
    st.caption(MODOS[modo])
    cfg.saida.incluir_diagnostico = st.checkbox(
        "Incluir colunas de diagnóstico", True,
        help="Handle, coordenadas e score da associação - é o que permite "
             "achar a posição no CAD para conferir.")

    st.divider()
    exe = localizar_oda(cfg.conversao.caminho_oda)
    if exe:
        st.success(f"ODA File Converter: `{exe.name}`")
    else:
        st.warning("ODA File Converter não encontrado — só arquivos **DXF** "
                   "poderão ser processados. Veja o README para instalar.")


# =============================================================================
# Entrada
# =============================================================================
aba_arquivo, aba_pasta = st.tabs(["Enviar arquivos", "Processar uma pasta"])

entrada: Path | None = None
temporaria: Path | None = None

with aba_arquivo:
    enviados = st.file_uploader(
        "Pranchas (.dxf ou .dwg)", type=["dxf", "dwg"], accept_multiple_files=True)
    if enviados:
        temporaria = Path(tempfile.mkdtemp(prefix="extrator_aco_ui_"))
        for arq in enviados:
            (temporaria / arq.name).write_bytes(arq.getbuffer())
        entrada = temporaria
        st.info(f"{len(enviados)} arquivo(s) prontos para processar.")

with aba_pasta:
    caminho_pasta = st.text_input(
        "Caminho da pasta com as pranchas",
        placeholder=r"C:\Projetos\Obra X\Pranchas")
    if caminho_pasta:
        p = Path(caminho_pasta)
        if p.exists():
            entrada = p
            st.info(f"Pasta encontrada: {p}")
        else:
            st.error("Pasta não encontrada.")


# =============================================================================
# Processamento
# =============================================================================
if st.button("Processar", type="primary", disabled=entrada is None,
             use_container_width=True):
    saida = Path(tempfile.mkdtemp(prefix="extrator_aco_saida_"))
    configurar_log(cfg.log, saida)
    cfg.projeto = (nome_projeto.strip()
                   or (entrada.stem if entrada.is_file() else entrada.name))

    with st.spinner("Lendo pranchas, associando textos e calculando..."):
        try:
            resultado = processar(entrada, cfg)
        except Exception as exc:
            st.error(f"Falha no processamento: {exc}")
            st.stop()

    e = resultado.estatisticas
    if not resultado.posicoes:
        st.error("Nenhuma posição de armadura foi extraída. Revise "
                 "`layers.texto_armadura` e `parser.padroes` no config.yaml.")

    df = montar_dataframe(resultado.posicoes, cfg)
    liquido = float(df["Peso (kg)"].sum()) if not df.empty else 0.0
    com_perda = float(df["Peso com perda (kg)"].sum()) if not df.empty else 0.0

    # --- indicadores -------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Peso líquido", f"{liquido:,.0f} kg".replace(",", "."))
    c2.metric(f"Com perda ({cfg.calculo.perda_percentual * 100:.0f}%)",
              f"{com_perda:,.0f} kg".replace(",", "."))
    c3.metric("Posições", e.posicoes_geradas)
    c4.metric("Trechos", e.areas_encontradas)
    c5.metric("Cortadas (fora do escopo)", e.posicoes_fora_escopo,
              help="Só é maior que zero no critério 'fora_do_escopo'. No "
                   "padrão 'maior_parte' a barra que cruza a divisa é "
                   "contada inteira no trecho onde ela mais está.")
    c6.metric("Fora de qualquer trecho", e.posicoes_sem_area,
              help="Armadura que não toca nenhum contorno: aqui falta "
                   "desenhar trecho.")

    # --- eficacia de cobertura dos trechos ---------------------------
    if not df.empty:
        fora = [cfg.areas.nome_sem_area, cfg.areas.nome_fora_escopo]
        base = "Peso com perda (kg)"
        dentro = float(df[~df["Area"].isin(fora)][base].sum())
        total = float(df[base].sum()) or 1.0
        eficacia = dentro / total
        if eficacia >= cfg.limites.eficacia_meta:
            st.success(f"Eficácia de cobertura: {eficacia * 100:.1f}% — "
                       "meta atingida, todo o aço está em trechos.")
        elif eficacia >= cfg.limites.eficacia_minima:
            st.warning(f"Eficácia de cobertura: {eficacia * 100:.1f}% — "
                       f"acima do mínimo de "
                       f"{cfg.limites.eficacia_minima * 100:.0f}%, "
                       f"mas ainda faltam {total - dentro:,.0f} kg em trechos."
                       .replace(",", "."))
        else:
            st.error(f"Eficácia de cobertura: {eficacia * 100:.1f}% — "
                     f"abaixo do mínimo de "
                     f"{cfg.limites.eficacia_minima * 100:.0f}%. "
                     f"{total - dentro:,.0f} kg não estão em nenhum trecho; "
                     "veja a aba COMPARAÇÃO FINAL.".replace(",", "."))

    erros = [i for i in resultado.inconsistencias if i.severidade.value == "ERRO"]
    alertas = [i for i in resultado.inconsistencias if i.severidade.value == "ALERTA"]
    if e.textos_nao_interpretados:
        st.error(f"{e.textos_nao_interpretados} texto(s) NÃO interpretados — "
                 "esse aço está fora do quantitativo. Veja INCONSISTÊNCIAS.")
    elif erros:
        st.warning(f"{len(erros)} erro(s) e {len(alertas)} alerta(s) a conferir.")
    else:
        st.success(f"Nenhum erro. {len(alertas)} alerta(s) para conferência.")

    # --- download ----------------------------------------------------
    destino = saida / "quantitativo_aco.xlsx"
    Exportador(cfg).exportar(resultado, destino)
    st.download_button("Baixar planilha (.xlsx)", destino.read_bytes(),
                       file_name="quantitativo_aco.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet",
                       use_container_width=True)

    # --- tabelas na tela ---------------------------------------------
    if not df.empty:
        # Na planilha enxuta a tela acompanha: os avisos ja sairam acima,
        # em uma linha. Repeti-los numa aba so aumentaria o que ha para ler.
        rotulos = ["Por trecho", "Por sentido", "Por bitola"]
        if not cfg.saida.modo_enxuto:
            rotulos += ["Inconsistências", "Detalhamento"]
        abas = dict(zip(rotulos, st.tabs(rotulos)))

        with abas["Por trecho"]:
            st.dataframe(resumo_por_area(df), use_container_width=True)
        with abas["Por sentido"]:
            st.dataframe(resumo_por_sentido(df), use_container_width=True)
        with abas["Por bitola"]:
            st.dataframe(resumo_por_bitola(df), use_container_width=True)
        if "Inconsistências" in abas:
            with abas["Inconsistências"]:
                if resultado.inconsistencias:
                    st.dataframe(pd.DataFrame([{
                        "Severidade": i.severidade.value, "Tipo": i.tipo.value,
                        "Descrição": i.descricao, "Prancha": i.prancha,
                        "Layer": i.layer, "Handle": i.handle, "Texto": i.texto,
                        "Ocorrências": i.ocorrencias,
                    } for i in resultado.inconsistencias]),
                        use_container_width=True)
                else:
                    st.success("Nenhuma inconsistência.")
            with abas["Detalhamento"]:
                st.dataframe(df, use_container_width=True)

    # --- log ----------------------------------------------------------
    log_path = saida / cfg.log.arquivo
    if log_path.is_file():
        with st.expander("Log detalhado do processamento"):
            st.code(log_path.read_text(encoding="utf-8"), language="text")

    if temporaria:
        shutil.rmtree(temporaria, ignore_errors=True)
