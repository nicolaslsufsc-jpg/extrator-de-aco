"""
Exportacao para Excel (xlsxwriter).

Estrutura do arquivo gerado:
    RESUMO GERAL      tabela mae, todas as areas somadas
    <uma por AREA>    mesmo layout, restrito ao trecho
    VERIFICACAO       soma das areas x tabela mae + consumo x limite
    INCONSISTENCIAS   tudo que exige conferencia humana

No MODO ENXUTO (`saida.modo_enxuto`) sobram so as abas de trecho e uma
aba CONFERENCIA, que confronta barra a barra com a tabela mestre. Todo o
resto vira uma observacao no topo da CONFERENCIA.

Formatacao: cabecalho congelado, autofiltro, colunas dimensionadas e
casas decimais consistentes (definidas em calculo.casas_decimais).
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pandas as pd
import xlsxwriter

from .calculo import (agrupar_por_posicao, eficacia_por_bitola,
                      montar_dataframe, resumo_por_area,
                      resumo_por_bitola)
from .config import Config
from .log_config import obter_log
from .modelos import ResultadoProcessamento, Severidade

# Colunas da tabela de resumo, na ordem pedida.
# Ordem da tabela de corte e dobra, igual a do projeto:
#   Pos | Bitola | Qtd | Dob. | Reta | Dob. | Comp.unit | Comp.total | Peso
COLUNAS = [
    ("Posicao", 12),
    ("Bitola (mm)", 12),
    ("Quantidade", 12),
    ("Dobra 1 (cm)", 11),
    ("Reta (cm)", 11),
    ("Dobra 2 (cm)", 11),
    ("Comprimento unitario (cm)", 20),
    ("Comprimento total (m)", 20),
    ("Peso (kg)", 12),
    ("Peso com perda (kg)", 18),
    ("Categoria", 11),
]

# Colunas que recebem soma nas linhas de subtotal e total. As de dobra
# NAO entram: somar medida de gancho nao significa nada.
COLUNAS_SOMADAS = ("Quantidade", "Comprimento total (m)", "Peso (kg)",
                   "Peso com perda (kg)")

COLUNAS_DIAGNOSTICO = [
    ("Qtd desenho", 13),
    ("Origem da qtd", 14),
    ("Texto no desenho", 30),
    ("Espacamento (cm)", 16),
    ("Comp. variavel", 14),
    ("Score associacao", 16),
    ("Handle texto", 13),
    ("Handle barra", 13),
    ("Layer", 20),
    ("X", 12),
    ("Y", 12),
]


# Abreviacoes usadas quando o nome do projeto + o nome da aba estouram o
# limite de 31 caracteres do Excel.
ABREVIACOES = {
    "RESUMO GERAL": "RESUMO",
    "VERIFICACAO": "VERIF",
    "INCONSISTENCIAS": "INCONSIST",
    "FORA_DO_ESCOPO": "FORA ESCOPO",
    "COMPARACAO FINAL": "COMPARACAO",
    "CONFERENCIA": "CONFER",
}

LIMITE_ABA = 31
SEPARADOR = " - "
# O prefixo do projeto nunca encolhe abaixo disto: um prefixo de 3 letras
# nao identifica obra nenhuma - nesse caso e melhor abreviar o sufixo.
MIN_PREFIXO = 8


def _limpar(nome: str) -> str:
    """Tira os caracteres que o Excel nao aceita em nome de aba."""
    return re.sub(r"[\[\]:*?/\\]", "-", str(nome)).strip()


def _prefixo_comum(projeto: str, sufixos: list[str]) -> str:
    """Corta o nome do projeto UMA vez, servindo a todas as abas.

    Se cada aba encurtasse o projeto por conta propria, a barra de abas
    ficaria com "Prancha Exemplo - ", "Prancha Exemp - ", "Prancha Exe - ":
    o mesmo projeto escrito de tres jeitos. Aqui o corte e unico, ditado
    pela aba de nome mais comprido.
    """
    projeto = _limpar(projeto)
    if not projeto or not sufixos:
        return projeto
    maior = max(len(_encurtar_sufixo(s)) for s in sufixos)
    espaco = LIMITE_ABA - len(SEPARADOR) - maior
    return projeto[:max(espaco, MIN_PREFIXO)].strip()


def _encurtar_sufixo(sufixo: str) -> str:
    """Nome curto conhecido da aba, quando existir."""
    return ABREVIACOES.get(sufixo.upper(), sufixo)


def _nome_aba(nome: str, usados: set[str], projeto: str = "") -> str:
    """Monta o nome da aba como "<projeto> - <nome>", dentro dos 31 caracteres.

    `projeto` aqui ja deve vir cortado por `_prefixo_comum`; o que sobrar
    de excesso e resolvido abreviando o sufixo, nunca o prefixo.
    """
    sufixo = _limpar(nome) or "AREA"
    projeto = _limpar(projeto)

    if projeto:
        if len(projeto) + len(SEPARADOR) + len(sufixo) > LIMITE_ABA:
            sufixo = _encurtar_sufixo(sufixo)
        espaco = LIMITE_ABA - len(SEPARADOR) - len(projeto)
        base = f"{projeto}{SEPARADOR}{sufixo[:espaco]}" if espaco >= 3 else sufixo
    else:
        base = sufixo

    base = base[:LIMITE_ABA]
    final, i = base, 2
    while final.upper() in usados:
        marca = f"~{i}"
        final = base[:LIMITE_ABA - len(marca)] + marca
        i += 1
    usados.add(final.upper())
    return final


class Exportador:
    """Escreve o .xlsx completo a partir do resultado do pipeline."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.log = obter_log()

    # ------------------------------------------------------------------
    def exportar(self, resultado: ResultadoProcessamento, destino: Path) -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)

        df = montar_dataframe(resultado.posicoes, self.cfg)

        # Todas as abas que serao criadas, para calcular o corte do prefixo
        # uma unica vez e manter o nome do projeto identico em todas elas.
        enxuto = self.cfg.saida.modo_enxuto
        limpo = self._modo_limpo()
        if enxuto:
            sufixos = ["CONFERENCIA"]
        else:
            sufixos = ["RESUMO GERAL", "COMPARACAO FINAL"]
            if not limpo:
                sufixos += ["VERIFICACAO", "INCONSISTENCIAS"]
        if self.cfg.saida.abas_por_area and not df.empty:
            sufixos += self._ordenar_areas(df)[:self.cfg.saida.max_abas_area]
        projeto = _prefixo_comum(self.cfg.projeto, sufixos)

        if projeto:
            self.log.info("Projeto (prefixo das abas): %s", projeto)
            if projeto != _limpar(self.cfg.projeto):
                self.log.info("  nome encurtado: o Excel limita a aba a %d "
                              "caracteres", LIMITE_ABA)
        self.log.info("Gerando %s", destino.name)

        wb = xlsxwriter.Workbook(str(destino), {"nan_inf_to_errors": True})
        try:
            self._formatos(wb)
            usados: set[str] = set()

            # --- 1. tabela mae -----------------------------------------
            # No modo enxuto ela nao existe: a planilha e a lista de corte
            # e dobra de cada trecho, mais a conferencia. Somar tudo de
            # novo numa aba mae seria justamente a informacao a mais.
            if not enxuto:
                subtitulo = self._subtitulo(resultado)
                if limpo:
                    subtitulo += "\n" + self._aviso_inconsistencias(resultado)
                self._aba_resumo(wb, _nome_aba("RESUMO GERAL", usados, projeto),
                                 df, titulo="RESUMO GERAL DE ACO",
                                 subtitulo=subtitulo)

            # --- 2. uma aba por area -----------------------------------
            areas_exportadas: list[str] = []
            if self.cfg.saida.abas_por_area and not df.empty:
                ordem = self._ordenar_areas(df)
                limite = self.cfg.saida.max_abas_area
                for nome in ordem[:limite]:
                    sub = df[df["Area"] == nome]
                    if sub.empty:
                        continue
                    pranchas = ", ".join(sorted(sub["Prancha"].unique()))
                    # Uma aba POR TRECHO, com o aco separado por sentido
                    # dentro dela - nunca uma aba por sentido.
                    self._aba_resumo(
                        wb, _nome_aba(nome, usados, projeto), sub,
                        titulo=f"TRECHO: {nome}",
                        subtitulo=f"Prancha(s) de origem: {pranchas}",
                        por_sentido=self.cfg.saida.agrupar_por_sentido,
                    )
                    areas_exportadas.append(nome)
                if len(ordem) > limite:
                    self.log.warning(
                        "%d area(s) alem do limite saida.max_abas_area=%d ficaram "
                        "so no RESUMO GERAL e na VERIFICACAO",
                        len(ordem) - limite, limite)

            # --- 3. conferencia contra a tabela mestre -----------------
            # No modo enxuto esta e a UNICA aba alem das de trecho.
            if enxuto:
                self._aba_conferencia(
                    wb, _nome_aba("CONFERENCIA", usados, projeto),
                    df, resultado, areas_exportadas)
                self.log.info("Modo enxuto: so as abas de trecho e a "
                              "CONFERENCIA; o detalhe continua no %s",
                              self.cfg.log.arquivo)
            else:
                self._aba_comparacao(
                    wb, _nome_aba("COMPARACAO FINAL", usados, projeto),
                    df, resultado)

                # --- 4 e 5. so no modo completo ------------------------
                # No modo limpo estas duas abas saem do arquivo; o balanco
                # de erros vira uma linha de aviso no topo do RESUMO GERAL
                # e o detalhe continua inteiro no extrator_aco.log.
                if not limpo:
                    self._aba_verificacao(
                        wb, _nome_aba("VERIFICACAO", usados, projeto), df,
                        areas_exportadas)
                    self._aba_inconsistencias(
                        wb, _nome_aba("INCONSISTENCIAS", usados, projeto),
                        resultado)
                else:
                    self.log.info("Modo limpo: VERIFICACAO e INCONSISTENCIAS "
                                  "nao foram geradas; veja o log para o detalhe")
        finally:
            wb.close()

        self.log.info("Arquivo gravado: %s", destino)
        return destino

    # ------------------------------------------------------------------
    def _modo_limpo(self) -> bool:
        """O modo enxuto e mais restrito que o limpo, entao inclui o limpo.

        Sem isso as abas de trecho do modo enxuto voltariam a trazer o
        bloco DETALHAMENTO e a coluna Prancha - o oposto do pedido.
        """
        return self.cfg.saida.modo_limpo or self.cfg.saida.modo_enxuto

    def _aviso_inconsistencias(self, resultado: ResultadoProcessamento) -> str:
        """Uma linha com o balanco, para o modo limpo nao esconder problema."""
        erros = sum(1 for i in resultado.inconsistencias
                    if i.severidade is Severidade.ERRO)
        alertas = sum(1 for i in resultado.inconsistencias
                      if i.severidade is Severidade.ALERTA)
        if not erros and not alertas:
            return "Nenhum erro ou alerta no processamento."
        return (f"ATENCAO: {erros} erro(s) e {alertas} alerta(s). Rode sem o "
                f"modo limpo para gerar a aba INCONSISTENCIAS, ou consulte "
                f"{self.cfg.log.arquivo}.")

    def _subtitulo(self, resultado: ResultadoProcessamento) -> str:
        e = resultado.estatisticas
        agora = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        prefixo = f"Projeto: {self.cfg.projeto}  |  " if self.cfg.projeto else ""
        return (prefixo
                + f"Prancha(s): {', '.join(resultado.pranchas) or '-'}  |  "
                f"Gerado em {agora}  |  "
                f"Perda: {self.cfg.calculo.perda_percentual * 100:.0f}%  |  "
                f"Criterio de divisa: {self.cfg.areas.criterio_divisa}  |  "
                f"{e.posicoes_geradas} posicoes")

    def _ordenar_areas(self, df: pd.DataFrame) -> list[str]:
        """Trechos de verdade primeiro; FORA_DO_ESCOPO e SEM_AREA no fim."""
        nomes = sorted(df["Area"].unique())
        finais = [self.cfg.areas.nome_fora_escopo, self.cfg.areas.nome_sem_area]
        cauda = [n for n in finais if n in nomes]
        return [n for n in nomes if n not in cauda] + cauda

    # ------------------------------------------------------------------
    def _formatos(self, wb: xlsxwriter.Workbook) -> None:
        c = self.cfg.saida.cores
        d = self.cfg.calculo.casas_decimais

        def num(casas: int) -> str:
            return "#,##0" if casas <= 0 else "#,##0." + "0" * casas

        self.f = {
            "titulo": wb.add_format({
                "bold": True, "font_size": 14, "font_color": "#FFFFFF",
                "bg_color": c.cabecalho, "align": "left", "valign": "vcenter"}),
            "subtitulo": wb.add_format({
                "italic": True, "font_size": 9, "font_color": "#444444"}),
            "cabecalho": wb.add_format({
                "bold": True, "font_color": "#FFFFFF", "bg_color": c.cabecalho,
                "align": "center", "valign": "vcenter", "text_wrap": True,
                "border": 1}),
            "texto": wb.add_format({"border": 1}),
            "texto_c": wb.add_format({"border": 1, "align": "center"}),
            "qtd": wb.add_format({"border": 1, "num_format": "#,##0.##",
                                  "align": "center"}),
            "comp_unit": wb.add_format({"border": 1,
                                        "num_format": num(d.comprimento_unitario)}),
            "comp_tot": wb.add_format({"border": 1,
                                       "num_format": num(d.comprimento_total)}),
            "peso": wb.add_format({"border": 1, "num_format": num(d.peso)}),
            "pct": wb.add_format({"border": 1, "num_format": "0." + "0" * d.percentual + "%",
                                  "align": "center"}),
            # subtotais e total
            "sub_txt": wb.add_format({"bold": True, "bg_color": c.subtotal,
                                      "border": 1}),
            "sub_num": wb.add_format({"bold": True, "bg_color": c.subtotal,
                                      "border": 1, "num_format": num(d.peso)}),
            "sub_comp": wb.add_format({"bold": True, "bg_color": c.subtotal,
                                       "border": 1,
                                       "num_format": num(d.comprimento_total)}),
            "sub_qtd": wb.add_format({"bold": True, "bg_color": c.subtotal,
                                      "border": 1, "num_format": "#,##0.##",
                                      "align": "center"}),
            "tot_txt": wb.add_format({"bold": True, "bg_color": c.cabecalho,
                                      "font_color": "#FFFFFF", "border": 1}),
            "tot_num": wb.add_format({"bold": True, "bg_color": c.cabecalho,
                                      "font_color": "#FFFFFF", "border": 1,
                                      "num_format": num(d.peso)}),
            "tot_comp": wb.add_format({"bold": True, "bg_color": c.cabecalho,
                                       "font_color": "#FFFFFF", "border": 1,
                                       "num_format": num(d.comprimento_total)}),
            # semaforo da verificacao
            "ok": wb.add_format({"bg_color": c.ok, "border": 1,
                                 "align": "center", "bold": True}),
            "alerta": wb.add_format({"bg_color": c.alerta, "border": 1,
                                     "align": "center", "bold": True}),
            "excedido": wb.add_format({"bg_color": c.excedido, "border": 1,
                                       "align": "center", "bold": True}),
            "sev_erro": wb.add_format({"bg_color": c.excedido, "border": 1,
                                       "bold": True, "align": "center"}),
            "sev_alerta": wb.add_format({"bg_color": c.alerta, "border": 1,
                                         "bold": True, "align": "center"}),
            "sev_info": wb.add_format({"bg_color": "#DDEBF7", "border": 1,
                                       "align": "center"}),
            # cabecalho das secoes de sentido dentro da aba do trecho
            "secao": wb.add_format({
                "bold": True, "font_size": 11, "font_color": "#FFFFFF",
                "bg_color": "#2E75B6", "align": "left",
                "valign": "vcenter", "indent": 1}),
        }

    # ==================================================================
    # ABA DE RESUMO (tabela mae e abas por area usam o mesmo layout)
    # ==================================================================
    def _aba_resumo(self, wb, nome: str, df: pd.DataFrame,
                    titulo: str, subtitulo: str,
                    por_sentido: bool = False) -> None:
        """Escreve uma aba de quantitativo.

        `por_sentido=True` divide o conteudo em secoes - uma por sentido da
        armadura (X, Y, inclinada) - cada uma com os proprios subtotais por
        bitola, e fecha com o total do trecho. E o formato pedido para as
        abas de trecho: UMA aba por trecho, com as duas direcoes dentro.
        """
        ws = wb.add_worksheet(nome)
        f = self.f
        limpo = self._modo_limpo()
        # As colunas sao SEMPRE as completas: a planilha e uma lista de
        # corte e dobra, entao posicao e comprimento unitario de cada barra
        # tem de aparecer mesmo no modo limpo.
        colunas = list(COLUNAS)
        if self.cfg.saida.incluir_prancha and not limpo:
            colunas.append(("Prancha", 22))
        ncol = len(colunas)

        ws.merge_range(0, 0, 0, ncol - 1, titulo, f["titulo"])
        ws.set_row(0, 24)
        ws.merge_range(1, 0, 1, ncol - 1, subtitulo, f["subtitulo"])
        for j, (_, largura) in enumerate(colunas):
            ws.set_column(j, j, largura)

        if df.empty:
            ws.write(3, 0, "Nenhuma posicao encontrada.", f["texto"])
            return

        linha = 3
        total = {"q": 0.0, "ct": 0.0, "p": 0.0, "pp": 0.0}
        primeira_cabecalho = None

        if por_sentido:
            for sentido in self._ordenar_sentidos(df):
                sub = df[df["Sentido"] == sentido]
                if sub.empty:
                    continue
                ws.merge_range(linha, 0, linha, ncol - 1,
                               f"{sentido}   -   {len(sub)} posicao(oes)",
                               f["secao"])
                ws.set_row(linha, 20)
                linha += 1
                linha, parcial, cab = self._escrever_bloco(
                    ws, sub, linha, colunas, df, rotulo_total=sentido)
                primeira_cabecalho = primeira_cabecalho or cab
                for k in total:
                    total[k] += parcial[k]
                linha += 1
        else:
            linha, total, primeira_cabecalho = self._escrever_bloco(
                ws, df, linha, colunas, df)

        # --- total da aba ---------------------------------------------
        rotulo = "TOTAL DO TRECHO" if por_sentido else "TOTAL GERAL"
        nomes = [c for c, _ in colunas]
        valores_tot = {"Posicao": rotulo,
                       "Quantidade": total["q"],
                       "Comprimento total (m)": total["ct"],
                       "Peso (kg)": total["p"],
                       "Peso com perda (kg)": total["pp"]}
        for j, nome in enumerate(nomes):
            v = valores_tot.get(nome)
            fmt = {"Comprimento total (m)": f["tot_comp"],
                   "Peso (kg)": f["tot_num"],
                   "Peso com perda (kg)": f["tot_num"]}.get(nome, f["tot_txt"])
            if v is None:
                ws.write_blank(linha, j, None, f["tot_txt"])
            elif isinstance(v, (int, float)):
                ws.write_number(linha, j, float(v), fmt)
            else:
                ws.write(linha, j, str(v), fmt)

        # --- por categoria --------------------------------------------
        linha += 2
        ws.write(linha, 0, "POR CATEGORIA", f["cabecalho"])
        ws.write(linha, 1, "Comp. total (m)", f["cabecalho"])
        ws.write(linha, 2, "Peso (kg)", f["cabecalho"])
        ws.write(linha, 3, "Peso c/ perda (kg)", f["cabecalho"])
        linha += 1
        for cat, g in df.groupby("Categoria"):
            ws.write(linha, 0, cat, f["texto"])
            ws.write_number(linha, 1, float(g["Comprimento total (m)"].sum()),
                            f["comp_tot"])
            ws.write_number(linha, 2, float(g["Peso (kg)"].sum()), f["peso"])
            ws.write_number(linha, 3, float(g["Peso com perda (kg)"].sum()),
                            f["peso"])
            linha += 1

        # --- resumo por sentido (so nas abas de trecho) ---------------
        if por_sentido:
            linha += 1
            ws.write(linha, 0, "RESUMO POR SENTIDO", f["cabecalho"])
            ws.write(linha, 1, "Posicoes", f["cabecalho"])
            ws.write(linha, 2, "Comp. total (m)", f["cabecalho"])
            ws.write(linha, 3, "Peso c/ perda (kg)", f["cabecalho"])
            ws.write(linha, 4, "% do trecho", f["cabecalho"])
            linha += 1
            base = float(df["Peso com perda (kg)"].sum()) or 1.0
            for sentido in self._ordenar_sentidos(df):
                sub = df[df["Sentido"] == sentido]
                if sub.empty:
                    continue
                ws.write(linha, 0, sentido, f["sub_txt"])
                ws.write_number(linha, 1, len(sub), f["texto_c"])
                ws.write_number(linha, 2,
                                float(sub["Comprimento total (m)"].sum()),
                                f["comp_tot"])
                ws.write_number(linha, 3,
                                float(sub["Peso com perda (kg)"].sum()), f["peso"])
                ws.write_number(linha, 4,
                                float(sub["Peso com perda (kg)"].sum()) / base,
                                f["pct"])
                linha += 1

        if primeira_cabecalho is not None:
            ws.freeze_panes(primeira_cabecalho + 1, 1)
            ws.autofilter(primeira_cabecalho, 0, primeira_cabecalho, ncol - 1)

        # O bloco linha-a-linha nao existe no modo limpo nem no enxuto.
        if self.cfg.saida.incluir_diagnostico and not limpo:
            self._bloco_detalhe(wb, ws, df, linha + 2, ncol)

    # ------------------------------------------------------------------
    def _ordenar_sentidos(self, df: pd.DataFrame) -> list[str]:
        """Sentidos presentes, na ordem fixa do config (X, Y, inclinado...)."""
        presentes = [str(x) for x in df["Sentido"].dropna().unique()]
        ordem = [s for s in self.cfg.sentido.ordem if s in presentes]
        return ordem + sorted(x for x in presentes if x not in ordem)

    # ------------------------------------------------------------------
    def _escrever_bloco(self, ws, sub: pd.DataFrame, linha: int,
                        colunas: list, df_completo: pd.DataFrame,
                        rotulo_total: str = "") -> tuple[int, dict, int]:
        """Escreve cabecalho + linhas + subtotais por bitola de um subconjunto.

        As celulas sao escritas por NOME de coluna, nunca por indice fixo.
        Inserir uma coluna no meio da tabela (foi o que aconteceu com as
        dobras) desalinharia silenciosamente todas as seguintes.

        Devolve (proxima_linha, totais, linha_do_cabecalho).
        """
        f = self.f
        nomes = [c for c, _ in colunas]
        idx = {nome: i for i, nome in enumerate(nomes)}
        lin_cab = linha
        for j, nome in enumerate(nomes):
            ws.write(lin_cab, j, nome, f["cabecalho"])
        ws.set_row(lin_cab, 30)
        linha = lin_cab + 1

        consolidado = agrupar_por_posicao(sub)
        bitola_atual = None
        acc = {c: 0.0 for c in COLUNAS_SOMADAS}
        tot = {c: 0.0 for c in COLUNAS_SOMADAS}

        # formato de cada coluna, por nome
        d = self.cfg.calculo.casas_decimais
        fmt_col = {
            "Posicao": f["texto_c"], "Bitola (mm)": f["texto_c"],
            "Quantidade": f["qtd"],
            "Dobra 1 (cm)": f["texto_c"], "Reta (cm)": f["texto_c"],
            "Dobra 2 (cm)": f["texto_c"],
            "Comprimento unitario (cm)": f["comp_unit"],
            "Comprimento total (m)": f["comp_tot"],
            "Peso (kg)": f["peso"], "Peso com perda (kg)": f["peso"],
            "Categoria": f["texto_c"], "Prancha": f["texto"],
        }

        def escreve(lin: int, valores: dict, formatos: dict) -> None:
            for nome in nomes:
                v = valores.get(nome)
                fmt = formatos.get(nome, f["texto"])
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    ws.write_blank(lin, idx[nome], None, fmt)
                elif isinstance(v, (int, float)):
                    ws.write_number(lin, idx[nome], float(v), fmt)
                else:
                    ws.write(lin, idx[nome], str(v), fmt)

        def subtotal(lin: int, bitola) -> int:
            valores = {"Posicao": f"Subtotal \u00d8{bitola:g} mm",
                       "Bitola (mm)": bitola}
            valores.update(acc)
            fmts = {n: f["sub_txt"] for n in nomes}
            fmts.update({"Quantidade": f["sub_qtd"],
                         "Comprimento total (m)": f["sub_comp"],
                         "Peso (kg)": f["sub_num"],
                         "Peso com perda (kg)": f["sub_num"]})
            escreve(lin, valores, fmts)
            return lin + 1

        for _, r in consolidado.iterrows():
            bit = r["Bitola (mm)"]
            if bitola_atual is not None and bit != bitola_atual:
                linha = subtotal(linha, bitola_atual)
                acc = {c: 0.0 for c in COLUNAS_SOMADAS}
            bitola_atual = bit

            valores = {nome: r[nome] for nome in nomes if nome in r.index}
            if "Prancha" in idx:
                sel = sub[(sub["Posicao"] == r["Posicao"])
                          & (sub["Bitola (mm)"] == bit)]
                valores["Prancha"] = ", ".join(sorted(sel["Prancha"].unique()))
            escreve(linha, valores, fmt_col)

            for c in COLUNAS_SOMADAS:
                acc[c] += float(r[c])
                tot[c] += float(r[c])
            linha += 1

        if bitola_atual is not None:
            linha = subtotal(linha, bitola_atual)

        if rotulo_total:
            valores = {"Posicao": f"Total {rotulo_total}"}
            valores.update(tot)
            fmts = {n: f["sub_txt"] for n in nomes}
            fmts.update({"Quantidade": f["sub_qtd"],
                         "Comprimento total (m)": f["sub_comp"],
                         "Peso (kg)": f["sub_num"],
                         "Peso com perda (kg)": f["sub_num"]})
            escreve(linha, valores, fmts)
            linha += 1

        # chaves curtas para quem chama continuar somando
        resumo = {"q": tot["Quantidade"], "ct": tot["Comprimento total (m)"],
                  "p": tot["Peso (kg)"], "pp": tot["Peso com perda (kg)"]}
        return linha + 1, resumo, lin_cab

    # ------------------------------------------------------------------
    def _bloco_detalhe(self, wb, ws, df: pd.DataFrame, linha: int,
                       ncols: int) -> None:
        """Lista bruta (uma linha por texto lido) abaixo do resumo.

        E este bloco que permite achar a posicao no CAD pelo handle e
        conferir uma leitura duvidosa. Escrito por NOME de coluna, para
        nao desalinhar quando a tabela ganha colunas novas.
        """
        f = self.f
        cabecalhos = ([c for c, _ in COLUNAS] + ["Area", "Sentido", "Prancha"]
                      + [c for c, _ in COLUNAS_DIAGNOSTICO])
        ws.merge_range(linha, 0, linha, max(ncols, len(cabecalhos)) - 1,
                       "DETALHAMENTO - uma linha por texto lido no desenho "
                       "(use o handle para localizar a entidade no CAD)",
                       f["titulo"])
        linha += 1
        for j, rotulo in enumerate(cabecalhos):
            ws.write(linha, j, rotulo, f["cabecalho"])
        inicio = linha + 1

        d = self.cfg.calculo.casas_decimais
        fmt_col = {
            "Comprimento unitario (cm)": f["comp_unit"],
            "Comprimento total (m)": f["comp_tot"],
            "Peso (kg)": f["peso"], "Peso com perda (kg)": f["peso"],
            "Quantidade": f["qtd"], "Qtd desenho": f["qtd"],
            "X": f["comp_tot"], "Y": f["comp_tot"],
        }
        centralizadas = {"Posicao", "Bitola (mm)", "Categoria", "Dobra 1 (cm)",
                         "Reta (cm)", "Dobra 2 (cm)", "Comp. variavel",
                         "Score associacao", "Handle texto", "Handle barra",
                         "Espacamento (cm)", "Origem da qtd", "Sentido"}

        ordenado = df.sort_values(["Area", "Bitola (mm)", "Posicao"])
        for i, (_, r) in enumerate(ordenado.iterrows()):
            L = inicio + i
            for j, nome in enumerate(cabecalhos):
                valor = r[nome] if nome in r.index else None
                fmt = fmt_col.get(nome,
                                  f["texto_c"] if nome in centralizadas
                                  else f["texto"])
                if valor is None or (isinstance(valor, float) and pd.isna(valor)):
                    ws.write_blank(L, j, None, fmt)
                elif isinstance(valor, (int, float)):
                    ws.write_number(L, j, float(valor), fmt)
                else:
                    ws.write(L, j, str(valor), fmt)

    # ==================================================================
    # ABA COMPARACAO FINAL - tabela mestre x total dos trechos
    # ==================================================================
    def _aba_comparacao(self, wb, nome: str, df: pd.DataFrame,
                        resultado: ResultadoProcessamento) -> None:
        """Mede quanto do aco extraido foi atribuido a um trecho nomeado.

            eficacia = peso dentro de trechos / peso total extraido

        Com todos os trechos da obra desenhados na layer certa, a eficacia
        tende a 100%. O que faltar esta em SEM_AREA (nenhum contorno cobre
        aquela armadura) ou em FORA_DO_ESCOPO (a barra atravessa a divisa
        de um trecho) - e a aba mostra os dois, para saber onde corrigir.
        """
        ws = wb.add_worksheet(nome)
        f = self.f
        lim = self.cfg.limites
        ws.set_column(0, 0, 34)
        ws.set_column(1, 6, 19)

        ws.merge_range(0, 0, 0, 6, "COMPARACAO FINAL", f["titulo"])
        ws.set_row(0, 24)
        base = ("Peso com perda (kg)"
                if lim.base_comparacao == "peso_com_perda" else "Peso (kg)")
        ws.merge_range(
            1, 0, 1, 6,
            "Bloco 1: % DE ACERTO - o que foi extraido das barras contra a "
            "tabela de aco desenhada na prancha (o gabarito).   "
            "Bloco 2: COBERTURA - quanto do extraido caiu dentro de um trecho.",
            f["subtitulo"])

        if df.empty:
            ws.write(3, 0, "Nenhuma posicao processada.", f["texto"])
            return

        fora = [self.cfg.areas.nome_sem_area, self.cfg.areas.nome_fora_escopo]
        tabela = eficacia_por_bitola(df, fora, base)

        linha = self._bloco_acerto(ws, df, resultado, 3)

        ws.merge_range(linha, 0, linha, 6,
                       "2. COBERTURA - QUANTO DO EXTRAIDO CAIU EM ALGUM TRECHO",
                       f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Bitola (mm)", "Total extraido (kg)",
                                    "Total nos trechos (kg)",
                                    "Fora dos trechos (kg)", "Cobertura",
                                    "Situacao"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1

        for _, r in tabela.iterrows():
            ws.write(linha, 0, f"\u00d8{r['Bitola (mm)']:g}", f["texto_c"])
            ws.write_number(linha, 1, float(r["Tabela mestre (kg)"]), f["peso"])
            ws.write_number(linha, 2, float(r["Total nos trechos (kg)"]), f["peso"])
            ws.write_number(linha, 3, float(r["Fora (kg)"]), f["peso"])
            ws.write_number(linha, 4, float(r["Eficacia"]), f["pct"])
            fmt, txt = self._situacao_eficacia(float(r["Eficacia"]))
            ws.write(linha, 5, txt, fmt)
            linha += 1

        mestre = float(df[base].sum())
        dentro = float(df[~df["Area"].isin(fora)][base].sum())
        eficacia = dentro / mestre if mestre else 0.0

        ws.write(linha, 0, "TOTAL", f["tot_txt"])
        ws.write_number(linha, 1, mestre, f["tot_num"])
        ws.write_number(linha, 2, dentro, f["tot_num"])
        ws.write_number(linha, 3, mestre - dentro, f["tot_num"])
        ws.write_number(linha, 4, eficacia, f["pct"])
        fmt, txt = self._situacao_eficacia(eficacia)
        ws.write(linha, 5, txt, fmt)
        linha += 2

        # --- onde esta o aco que ficou de fora -------------------------
        ws.merge_range(linha, 0, linha, 6,
                       "ONDE ESTA O ACO QUE NAO ENTROU EM NENHUM TRECHO",
                       f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Categoria", "Peso (kg)", "% do total",
                                    "Como resolver"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1
        ajuda = {
            self.cfg.areas.nome_sem_area:
                "Desenhe um contorno de TRECHO cobrindo esta regiao",
            self.cfg.areas.nome_fora_escopo:
                "A barra atravessa a divisa: ajuste o contorno para conte-la "
                "inteira, ou use --criterio proporcional",
        }
        for categoria in fora:
            sub = df[df["Area"] == categoria]
            if sub.empty:
                continue
            peso = float(sub[base].sum())
            ws.write(linha, 0, categoria, f["sub_txt"])
            ws.write_number(linha, 1, peso, f["peso"])
            ws.write_number(linha, 2, peso / mestre if mestre else 0, f["pct"])
            ws.write(linha, 3, ajuda.get(categoria, ""), f["texto"])
            linha += 1
        if mestre - dentro <= 0.01:
            ws.write(linha, 0, "Nada fora: 100% do aco esta em trechos.",
                     f["ok"])
            linha += 1
        linha += 1

        # --- peso por trecho ------------------------------------------
        ws.merge_range(linha, 0, linha, 6, "PESO POR TRECHO", f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Trecho", "Peso (kg)", "% do total",
                                    "Posicoes", "Sentidos"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1
        for area in self._ordenar_areas(df):
            sub = df[df["Area"] == area]
            peso = float(sub[base].sum())
            e_fora = area in fora
            ws.write(linha, 0, area, f["texto"] if not e_fora else f["sub_txt"])
            ws.write_number(linha, 1, peso, f["peso"])
            ws.write_number(linha, 2, peso / mestre if mestre else 0, f["pct"])
            ws.write_number(linha, 3, len(sub), f["texto_c"])
            ws.write(linha, 4, ", ".join(self._ordenar_sentidos(sub)), f["texto"])
            linha += 1

        ws.freeze_panes(4, 0)

    # ------------------------------------------------------------------
    def _bloco_acerto(self, ws, df: pd.DataFrame,
                      resultado: ResultadoProcessamento, linha: int) -> int:
        """Extraido x tabela mestre do desenho, bitola a bitola.

        A tabela desenhada e o GABARITO: e o que o projeto declara que a
        obra tem. O % de acerto mede quanto disso o programa conseguiu ler
        das barras. Comparacao feita em PESO LIQUIDO - a tabela do Eberick
        nao tem perda embutida.
        """
        from .tabela_mestre import totais_por_bitola

        f = self.f
        cfg_tm = self.cfg.tabela_mestre
        ws.merge_range(linha, 0, linha, 6,
                       "1. % DE ACERTO - EXTRAIDO x TABELA MESTRE DO DESENHO",
                       f["titulo"])
        linha += 1

        if not resultado.tabela_mestre:
            motivo = ("leitura da tabela mestre desligada em "
                      "tabela_mestre.ativar" if not cfg_tm.ativar else
                      "nenhuma tabela de aco foi encontrada nas layers "
                      f"{', '.join(cfg_tm.layers)}")
            ws.merge_range(linha, 0, linha, 6,
                           f"Sem gabarito para comparar: {motivo}.", f["texto"])
            return linha + 2

        for j, rotulo in enumerate(["Bitola (mm)", "Tabela mestre (kg)",
                                    "Extraido (kg)", "Diferenca (kg)",
                                    "% de acerto", "Situacao"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1

        mestre = totais_por_bitola(resultado.tabela_mestre)
        extraido = (df.groupby("Bitola (mm)")["Peso (kg)"].sum().to_dict()
                    if not df.empty else {})

        soma_mestre = soma_extraido = 0.0
        for bitola in sorted(set(mestre) | set(extraido)):
            kg_mestre = mestre.get(bitola, {}).get("peso_kg", 0.0)
            kg_extraido = float(extraido.get(bitola, 0.0))
            soma_mestre += kg_mestre
            soma_extraido += kg_extraido
            acerto = kg_extraido / kg_mestre if kg_mestre else 0.0

            ws.write(linha, 0, f"\u00d8{bitola:g}", f["texto_c"])
            ws.write_number(linha, 1, kg_mestre, f["peso"])
            ws.write_number(linha, 2, kg_extraido, f["peso"])
            ws.write_number(linha, 3, kg_extraido - kg_mestre, f["peso"])
            if kg_mestre:
                ws.write_number(linha, 4, acerto, f["pct"])
                fmt, txt = self._situacao_acerto(acerto)
            else:
                ws.write(linha, 4, "-", f["texto_c"])
                fmt, txt = f["alerta"], "SO NO EXTRAIDO"
            ws.write(linha, 5, txt, fmt)
            linha += 1

        acerto_total = soma_extraido / soma_mestre if soma_mestre else 0.0
        ws.write(linha, 0, "TOTAL", f["tot_txt"])
        ws.write_number(linha, 1, soma_mestre, f["tot_num"])
        ws.write_number(linha, 2, soma_extraido, f["tot_num"])
        ws.write_number(linha, 3, soma_extraido - soma_mestre, f["tot_num"])
        ws.write_number(linha, 4, acerto_total, f["pct"])
        fmt, txt = self._situacao_acerto(acerto_total)
        ws.write(linha, 5, txt, fmt)
        linha += 2

        ws.merge_range(
            linha, 0, linha, 6,
            f"Gabarito lido da prancha: {len(resultado.tabela_mestre)} "
            f"posicao(oes), {soma_mestre:,.1f} kg. Comparacao em peso LIQUIDO "
            f"(a tabela do projeto nao traz perda). Acerto abaixo de "
            f"{cfg_tm.acerto_minimo * 100:.0f}% costuma significar prancha "
            f"faltando no lote, texto nao interpretado ou armadura declarada "
            f"so como nota (malha/tela).".replace(",", "."),
            f["subtitulo"])
        return linha + 2

    def _situacao_acerto(self, valor: float):
        """Semaforo do % de acerto contra o gabarito."""
        cfg_tm = self.cfg.tabela_mestre
        if valor > 1.0 + (1.0 - cfg_tm.acerto_meta):
            return self.f["excedido"], "EXTRAIU A MAIS"
        if valor >= cfg_tm.acerto_meta:
            return self.f["ok"], "CONFERE"
        if valor >= cfg_tm.acerto_minimo:
            return self.f["alerta"], "ACEITAVEL"
        return self.f["excedido"], "ABAIXO DO MINIMO"

    def _situacao_eficacia(self, valor: float):
        """Semaforo da eficacia: meta / aceitavel / abaixo do minimo."""
        lim = self.cfg.limites
        if valor >= lim.eficacia_meta:
            return self.f["ok"], "META ATINGIDA"
        if valor >= lim.eficacia_minima:
            return self.f["alerta"], "ACEITAVEL"
        return self.f["excedido"], "ABAIXO DO MINIMO"

    # ==================================================================
    # ABA VERIFICACAO
    # ==================================================================
    # ==================================================================
    # ABA DE CONFERENCIA (modo enxuto)
    # ==================================================================
    # Tolerancia do comprimento unitario, em cm. Mesma folga usada em
    # rateio.aplicar_formato_do_gabarito: abaixo disso e arredondamento
    # de desenho, nao barra diferente.
    TOLERANCIA_COMPRIMENTO_CM = 1.0

    def _aba_conferencia(self, wb, nome: str, df: pd.DataFrame,
                         resultado: ResultadoProcessamento,
                         areas_exportadas: list[str]) -> None:
        """Cada barra desenhada consta na tabela mestre do projeto?

        Uma linha por (trecho, posicao, bitola, comprimento). A pergunta
        que a aba responde e de identidade da barra: a posicao existe na
        tabela do projeto e com o mesmo comprimento unitario?

        A QUANTIDADE aparece ao lado, mas NAO reprova nada. O fluxo normal
        e recortar o desenho num trecho e deixar a tabela mestre descrevendo
        o pavimento inteiro - divergir de quantidade ali e o esperado, nao
        defeito.
        """
        ws = wb.add_worksheet(nome)
        f = self.f
        colunas = [("Trecho", 26), ("Posicao", 12), ("Bitola (mm)", 12),
                   ("Qtd no desenho", 15), ("Comp. unit. desenho (cm)", 22),
                   ("Comp. unit. tabela (cm)", 22), ("Qtd na tabela", 14),
                   ("Situacao", 24)]
        ncol = len(colunas)
        for j, (_, largura) in enumerate(colunas):
            ws.set_column(j, j, largura)

        ws.merge_range(0, 0, 0, ncol - 1,
                       "CONFERENCIA - BARRAS DESENHADAS x TABELA DO PROJETO",
                       f["titulo"])
        ws.set_row(0, 24)
        ws.merge_range(1, 0, 1, ncol - 1, self._subtitulo(resultado),
                       f["subtitulo"])

        linhas = self._linhas_conferencia(df, resultado)

        # --- observacao: o unico lugar onde problema e reportado -------
        fmt, texto = self._observacao_conferencia(resultado, linhas,
                                                  df, areas_exportadas)
        ws.merge_range(2, 0, 2, ncol - 1, texto, fmt)
        ws.set_row(2, 30)

        if df.empty:
            ws.write(4, 0, "Nenhuma posicao processada.", f["texto"])
            return

        linha = 4
        for j, (rotulo, _) in enumerate(colunas):
            ws.write(linha, j, rotulo, f["cabecalho"])
        cabecalho = linha
        linha += 1

        for r in linhas:
            ws.write(linha, 0, r["trecho"], f["texto"])
            ws.write(linha, 1, r["posicao"], f["texto_c"])
            ws.write_number(linha, 2, r["bitola"], f["texto_c"])
            ws.write_number(linha, 3, r["qtd_desenho"], f["qtd"])
            ws.write_number(linha, 4, r["comp_desenho"], f["comp_unit"])
            if r["comp_tabela"] is None:
                ws.write(linha, 5, "-", f["texto_c"])
            else:
                ws.write_number(linha, 5, r["comp_tabela"], f["comp_unit"])
            if r["qtd_tabela"] is None:
                ws.write(linha, 6, "-", f["texto_c"])
            else:
                ws.write_number(linha, 6, r["qtd_tabela"], f["qtd"])
            ws.write(linha, 7, r["situacao"], f[r["formato"]])
            linha += 1

        ws.freeze_panes(cabecalho + 1, 2)
        ws.autofilter(cabecalho, 0, cabecalho, ncol - 1)

        # --- balanco ---------------------------------------------------
        linha += 1
        contagem = self._contar_situacoes(linhas)
        ws.write(linha, 0, "BALANCO", f["cabecalho"])
        ws.write(linha, 1, "Barras", f["cabecalho"])
        linha += 1
        for rotulo, chave, formato in [
                ("Conferem com a tabela", "ok", "ok"),
                ("Comprimento diferente", "comprimento", "alerta"),
                ("Nao constam na tabela", "ausente", "excedido"),
                ("Sem comparacao possivel (VAR.)", "variavel", "alerta")]:
            if not contagem[chave] and chave in ("variavel",):
                continue
            ws.write(linha, 0, rotulo, f["texto"])
            ws.write_number(linha, 1, contagem[chave], f[formato])
            linha += 1

        # --- por que a quantidade nao reprova --------------------------
        linha += 1
        ws.merge_range(
            linha, 0, linha, ncol - 1,
            "A coluna de quantidade e informativa: o desenho costuma ser um "
            "recorte de um trecho, enquanto a tabela do projeto descreve o "
            "pavimento inteiro. Diferenca de quantidade ali e esperada. O que "
            "vale conferir e a IDENTIDADE da barra: posicao, bitola e "
            "comprimento unitario.", f["subtitulo"])

    # ------------------------------------------------------------------
    def _linhas_conferencia(self, df: pd.DataFrame,
                            resultado: ResultadoProcessamento) -> list[dict]:
        """Confronta cada barra desenhada com a tabela mestre.

        Agrupa por (trecho, posicao, bitola, comprimento unitario): a mesma
        posicao aparece varias vezes no desenho, uma por faixa de
        distribuicao, e listar cada ocorrencia repetiria a mesma pergunta.
        """
        if df.empty:
            return []

        # A tabela mestre guarda a posicao sem o "N" que o desenho usa.
        por_chave = {(str(l.posicao), round(float(l.bitola_mm), 3)): l
                     for l in resultado.tabela_mestre}

        chaves = ["Area", "Posicao", "Bitola (mm)", "Comprimento unitario (cm)"]
        agrupado = (df.groupby(chaves, dropna=False)["Quantidade"]
                    .sum().reset_index())

        linhas = []
        for _, r in agrupado.iterrows():
            rotulo = str(r["Posicao"])
            bitola = float(r["Bitola (mm)"])
            comp = float(r["Comprimento unitario (cm)"])
            mestre = por_chave.get((rotulo.lstrip("Nn"), round(bitola, 3)))

            if mestre is None:
                situacao, formato = "NAO CONSTA NA TABELA", "excedido"
                comp_tab = qtd_tab = None
            else:
                comp_tab = mestre.comprimento_unitario_cm
                qtd_tab = float(mestre.quantidade)
                if mestre.variavel or not comp_tab:
                    situacao, formato = "TABELA: MEDIDA VARIAVEL", "alerta"
                elif abs(comp_tab - comp) > self.TOLERANCIA_COMPRIMENTO_CM:
                    situacao, formato = "COMPRIMENTO DIFERENTE", "alerta"
                else:
                    situacao, formato = "CONFERE", "ok"

            linhas.append({
                "trecho": str(r["Area"]),
                "posicao": rotulo,
                "bitola": bitola,
                "qtd_desenho": float(r["Quantidade"]),
                "comp_desenho": comp,
                "comp_tabela": comp_tab,
                "qtd_tabela": qtd_tab,
                "situacao": situacao,
                "formato": formato,
            })
        return linhas

    # ------------------------------------------------------------------
    @staticmethod
    def _contar_situacoes(linhas: list[dict]) -> dict:
        por_situacao = {"ok": 0, "comprimento": 0, "ausente": 0, "variavel": 0}
        chave = {"CONFERE": "ok",
                 "COMPRIMENTO DIFERENTE": "comprimento",
                 "NAO CONSTA NA TABELA": "ausente",
                 "TABELA: MEDIDA VARIAVEL": "variavel"}
        for r in linhas:
            por_situacao[chave[r["situacao"]]] += 1
        return por_situacao

    # ------------------------------------------------------------------
    def _observacao_conferencia(self, resultado: ResultadoProcessamento,
                                linhas: list[dict], df: pd.DataFrame,
                                areas_exportadas: list[str]) -> tuple:
        """A UNICA linha de aviso do modo enxuto.

        Sem aba de inconsistencias, um problema so tem este lugar para
        aparecer - entao ele nao pode ser omitido nem virar paragrafo.
        """
        f = self.f
        avisos: list[str] = []

        if not resultado.tabela_mestre:
            return (f["alerta"],
                    "Nenhuma tabela de aco foi lida na prancha: nao ha contra "
                    "o que conferir. As abas de trecho continuam validas; "
                    f"o motivo esta no {self.cfg.log.arquivo}.")

        c = self._contar_situacoes(linhas)
        if c["ausente"]:
            avisos.append(f"{c['ausente']} barra(s) NAO constam na tabela do "
                          f"projeto")
        if c["comprimento"]:
            avisos.append(f"{c['comprimento']} com comprimento diferente do "
                          f"da tabela")

        nao_lidos = resultado.estatisticas.textos_nao_interpretados
        if nao_lidos:
            avisos.append(f"{nao_lidos} texto(s) de armadura nao foram "
                          f"interpretados - esse aco esta FORA da planilha")

        sem_area = [self.cfg.areas.nome_sem_area,
                    self.cfg.areas.nome_fora_escopo]
        if not df.empty:
            soltas = int((df["Area"].isin(sem_area)).sum())
            if soltas:
                avisos.append(f"{soltas} barra(s) fora de qualquer trecho")

        if self.cfg.saida.abas_por_area and not df.empty:
            faltando = len(self._ordenar_areas(df)) - len(areas_exportadas)
            if faltando > 0:
                avisos.append(f"{faltando} trecho(s) sem aba propria (limite "
                              f"saida.max_abas_area)")

        if not avisos:
            return (f["ok"],
                    f"Nenhum problema: as {len(linhas)} barra(s) desenhadas "
                    f"constam na tabela do projeto, com o mesmo comprimento.")

        formato = f["excedido"] if (c["ausente"] or nao_lidos) else f["alerta"]
        return (formato, "CONFERIR: " + "; ".join(avisos)
                + f".  Detalhe completo no {self.cfg.log.arquivo}.")

    # ------------------------------------------------------------------
    def _aba_verificacao(self, wb, nome: str, df: pd.DataFrame,
                         areas_exportadas: list[str]) -> None:
        ws = wb.add_worksheet(nome)
        f = self.f
        ws.set_column(0, 0, 28)
        ws.set_column(1, 7, 17)

        ws.merge_range(0, 0, 0, 7, "VERIFICACAO", f["titulo"])
        ws.set_row(0, 24)
        base = self.cfg.limites.base_comparacao
        col_base = "Peso com perda (kg)" if base == "peso_com_perda" else "Peso (kg)"
        ws.merge_range(1, 0, 1, 7,
                       f"Base de comparacao com os limites: {col_base}  |  "
                       f"Alerta a partir de "
                       f"{self.cfg.limites.percentual_alerta * 100:.0f}% do limite",
                       f["subtitulo"])

        linha = 3
        # ---------------- Bloco 1: soma das areas x tabela mae --------
        ws.merge_range(linha, 0, linha, 7,
                       "1. CONFERENCIA: SOMA DAS AREAS x TABELA MAE", f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Bitola (mm)", "Tabela mae (kg)",
                                    "Soma das areas (kg)", "Diferenca (kg)",
                                    "Situacao"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1

        if df.empty:
            ws.write(linha, 0, "Nenhuma posicao processada.", f["texto"])
            linha += 1
        else:
            por_bit = resumo_por_bitola(df)
            # A "soma das areas" percorre exatamente as mesmas linhas do
            # RESUMO GERAL agrupadas por area: se as fracoes do criterio
            # proporcional estiverem certas, a diferenca e zero.
            por_area_bit = resumo_por_area(df)
            for _, r in por_bit.iterrows():
                bit = r["Bitola (mm)"]
                mae = float(r[col_base])
                soma = float(por_area_bit.loc[
                    por_area_bit["Bitola (mm)"] == bit, col_base].sum())
                dif = soma - mae
                ws.write(linha, 0, f"Ø{bit:g}", f["texto_c"])
                ws.write_number(linha, 1, mae, f["peso"])
                ws.write_number(linha, 2, soma, f["peso"])
                ws.write_number(linha, 3, dif, f["peso"])
                ok = abs(dif) < max(0.01, mae * 1e-6)
                ws.write(linha, 4, "OK" if ok else "DIVERGENTE",
                         f["ok"] if ok else f["excedido"])
                linha += 1

            total_mae = float(df[col_base].sum())
            total_areas = float(por_area_bit[col_base].sum())
            ws.write(linha, 0, "TOTAL", f["tot_txt"])
            ws.write_number(linha, 1, total_mae, f["tot_num"])
            ws.write_number(linha, 2, total_areas, f["tot_num"])
            ws.write_number(linha, 3, total_areas - total_mae, f["tot_num"])
            ok = abs(total_areas - total_mae) < max(0.01, total_mae * 1e-6)
            ws.write(linha, 4, "OK" if ok else "DIVERGENTE",
                     f["ok"] if ok else f["excedido"])
            linha += 2

        # ---------------- Bloco 2: consumo x limite -------------------
        ws.merge_range(linha, 0, linha, 7,
                       "2. CONSUMO POR AREA x LIMITE MAXIMO PREVISTO", f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Area", "Bitola", "Consumo (kg)",
                                    "Limite (kg)", "% consumido", "Situacao",
                                    "Folga (kg)"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1

        if df.empty:
            ws.write(linha, 0, "Nenhuma posicao processada.", f["texto"])
            linha += 1
        else:
            por_area_bit = resumo_por_area(df)
            for area in self._ordenar_areas(df):
                sub = por_area_bit[por_area_bit["Area"] == area]
                limite_cfg = self.cfg.limites.por_area.get(area)

                # linha TOTAL da area
                consumo = float(sub[col_base].sum())
                lim = limite_cfg.total if limite_cfg else None
                linha = self._linha_limite(ws, linha, area, "TOTAL", consumo, lim)

                # linhas por bitola, quando houver limite declarado
                for _, r in sub.iterrows():
                    bit = r["Bitola (mm)"]
                    lim_b = (limite_cfg.por_bitola.get(bit)
                             if limite_cfg else None)
                    linha = self._linha_limite(
                        ws, linha, "", f"Ø{bit:g}", float(r[col_base]), lim_b)

        # ---------------- Bloco 3: areas sem aba ----------------------
        if areas_exportadas is not None:
            faltando = [a for a in (self._ordenar_areas(df) if not df.empty else [])
                        if a not in areas_exportadas]
            if faltando:
                linha += 1
                ws.merge_range(linha, 0, linha, 7,
                               "Areas sem aba propria (limite saida.max_abas_area): "
                               + ", ".join(faltando), f["subtitulo"])

        ws.freeze_panes(4, 0)

    def _linha_limite(self, ws, linha: int, area: str, rotulo: str,
                      consumo: float, limite) -> int:
        f = self.f
        ws.write(linha, 0, area, f["sub_txt"] if area else f["texto"])
        ws.write(linha, 1, rotulo, f["sub_txt"] if area else f["texto_c"])
        ws.write_number(linha, 2, consumo,
                        f["sub_num"] if area else f["peso"])
        if limite is None or limite <= 0:
            ws.write(linha, 3, "sem limite", f["texto_c"])
            ws.write(linha, 4, "-", f["texto_c"])
            ws.write(linha, 5, "NAO VERIFICADO", f["texto_c"])
            ws.write(linha, 6, "-", f["texto_c"])
            return linha + 1

        pct = consumo / limite
        if pct > 1.0:
            fmt, situacao = f["excedido"], "EXCEDIDO"
        elif pct >= self.cfg.limites.percentual_alerta:
            fmt, situacao = f["alerta"], "PROXIMO DO LIMITE"
        else:
            fmt, situacao = f["ok"], "DENTRO DO LIMITE"
        ws.write_number(linha, 3, float(limite), f["peso"])
        ws.write_number(linha, 4, pct, f["pct"])
        ws.write(linha, 5, situacao, fmt)
        ws.write_number(linha, 6, float(limite) - consumo, f["peso"])
        return linha + 1

    # ==================================================================
    # ABA INCONSISTENCIAS
    # ==================================================================
    def _aba_inconsistencias(self, wb, nome: str,
                             resultado: ResultadoProcessamento) -> None:
        ws = wb.add_worksheet(nome)
        f = self.f
        colunas = [("Severidade", 12), ("Tipo", 42), ("Descricao", 80),
                   ("Prancha", 22), ("Layer", 22), ("Handle", 12),
                   ("Texto no desenho", 32), ("X", 12), ("Y", 12),
                   ("Ocorrencias", 12)]

        ws.merge_range(0, 0, 0, len(colunas) - 1, "INCONSISTENCIAS", f["titulo"])
        ws.set_row(0, 24)
        ws.merge_range(
            1, 0, 1, len(colunas) - 1,
            "ERRO = o quantitativo esta errado ou incompleto  |  "
            "ALERTA = pode estar errado, exige conferencia no CAD  |  "
            "INFO = informativo. Localize a entidade no AutoCAD pelo Handle.",
            f["subtitulo"])

        # ---- resumo por tipo: abre a aba com o balanco, nao com a lista --
        # Sem isso, 22 linhas do mesmo aviso dao a impressao de 22 problemas
        # diferentes. O detalhe continua logo abaixo, nada e escondido.
        fmt_sev = {Severidade.ERRO: f["sev_erro"],
                   Severidade.ALERTA: f["sev_alerta"],
                   Severidade.INFO: f["sev_info"]}

        contagem: dict[tuple, int] = {}
        for inc in resultado.inconsistencias:
            chave = (inc.severidade, inc.tipo)
            contagem[chave] = contagem.get(chave, 0) + inc.ocorrencias

        linha = 3
        ws.merge_range(linha, 0, linha, len(colunas) - 1,
                       "RESUMO POR TIPO", f["titulo"])
        linha += 1
        for j, rotulo in enumerate(["Severidade", "Tipo", "Ocorrencias"]):
            ws.write(linha, j, rotulo, f["cabecalho"])
        linha += 1

        ordem = {Severidade.ERRO: 0, Severidade.ALERTA: 1, Severidade.INFO: 2}
        if contagem:
            for (sev, tipo), n in sorted(
                    contagem.items(), key=lambda kv: (ordem.get(kv[0][0], 3), -kv[1])):
                ws.write(linha, 0, sev.value, fmt_sev.get(sev, f["texto_c"]))
                ws.write(linha, 1, tipo.value, f["texto"])
                ws.write_number(linha, 2, n, f["texto_c"])
                linha += 1
        else:
            ws.write(linha, 0, "Nenhuma inconsistencia encontrada.", f["ok"])
            linha += 1

        linha += 1
        ws.merge_range(linha, 0, linha, len(colunas) - 1,
                       "DETALHE - uma linha por ocorrencia", f["titulo"])
        lin_cab = linha + 1
        for j, (rotulo, largura) in enumerate(colunas):
            ws.write(lin_cab, j, rotulo, f["cabecalho"])
            ws.set_column(j, j, largura)
        itens = sorted(resultado.inconsistencias,
                       key=lambda i: (ordem.get(i.severidade, 3), i.tipo.value))

        linha = lin_cab + 1
        for inc in itens:
            ws.write(linha, 0, inc.severidade.value,
                     fmt_sev.get(inc.severidade, f["texto_c"]))
            ws.write(linha, 1, inc.tipo.value, f["texto"])
            ws.write(linha, 2, inc.descricao, f["texto"])
            ws.write(linha, 3, inc.prancha, f["texto"])
            ws.write(linha, 4, inc.layer, f["texto"])
            ws.write(linha, 5, inc.handle, f["texto_c"])
            ws.write(linha, 6, inc.texto, f["texto"])
            ws.write(linha, 7, "" if inc.x is None else round(inc.x, 3), f["texto_c"])
            ws.write(linha, 8, "" if inc.y is None else round(inc.y, 3), f["texto_c"])
            ws.write_number(linha, 9, inc.ocorrencias, f["texto_c"])
            linha += 1

        if not itens:
            ws.write(lin_cab + 1, 0, "Nenhuma inconsistencia encontrada.",
                     f["ok"])
            linha = lin_cab + 2

        ws.autofilter(lin_cab, 0, max(linha - 1, lin_cab), len(colunas) - 1)

        # --- estatisticas do processamento no rodape ------------------
        e = resultado.estatisticas
        linha += 2
        ws.merge_range(linha, 0, linha, len(colunas) - 1,
                       "ESTATISTICAS DO PROCESSAMENTO", f["titulo"])
        linha += 1
        pares = [
            ("Arquivos lidos", e.arquivos_lidos),
            ("Entidades no desenho", e.entidades_totais),
            ("Textos lidos", e.textos_lidos),
            ("Textos interpretados", e.textos_interpretados),
            ("Textos descartados como ruido (parser.ignorar_textos)",
             e.textos_ignorados_ruido),
            ("Textos em layers ignoradas (layers.ignorar)",
             e.textos_em_layers_ignoradas),
            ("Textos NAO interpretados", e.textos_nao_interpretados),
            ("Geometrias lidas", e.geometrias_lidas),
            ("Geometrias qualificadas como barra", e.geometrias_barra),
            ("Associacoes texto-barra ok", e.associacoes_ok),
            ("Associacoes duvidosas", e.associacoes_duvidosas),
            ("Textos sem barra associada", e.associacoes_falharam),
            ("Areas encontradas", e.areas_encontradas),
            ("Posicoes geradas", e.posicoes_geradas),
            ("Posicoes fora de qualquer area", e.posicoes_sem_area),
            ("Posicoes cortadas pelo contorno (fora do escopo)",
             e.posicoes_fora_escopo),
            ("Altura mediana do texto (unidades)",
             round(e.altura_texto_mediana or 0, 4)),
            ("Escala estimada (cm reais por unidade)",
             round(e.escala_estimada, 2) if e.escala_estimada else "nao estimada"),
            ("Tempo de processamento (s)", round(e.tempo_s, 2)),
        ]
        for rotulo, valor in pares:
            ws.write(linha, 0, rotulo, f["sub_txt"])
            ws.write(linha, 1, valor, f["texto"])
            linha += 1

        if e.posicoes_por_layer:
            linha += 1
            ws.write(linha, 0, "Posicoes por layer de origem", f["cabecalho"])
            linha += 1
            for layer, n in sorted(e.posicoes_por_layer.items(),
                                   key=lambda kv: -kv[1]):
                ws.write(linha, 0, layer, f["texto"])
                ws.write_number(linha, 1, n, f["texto_c"])
                linha += 1
