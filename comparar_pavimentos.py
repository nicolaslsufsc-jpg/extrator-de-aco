"""
Aproveitamento de aco entre pavimentos - corte e dobra.

PROBLEMA QUE RESOLVE
--------------------
Comprou-se a lista inteira de aco de um pavimento (PILOTIS), mas so parte
dele foi executada. O que sobrou esta no canteiro JA CORTADO E DOBRADO.
A pergunta e: quanto desse estoque serve, sem retrabalho, para a lista de
outro pavimento (2o PAVIMENTO)?

REGRA DE INTERCAMBIO
--------------------
Uma peca so substitui outra se for IDENTICA:

    mesma bitola  +  mesmo comprimento unitario  +  mesmo formato de dobras

Duas barras de 111 cm com dobras "9+93+9" e "20+71+20" tem o mesmo peso e
o mesmo comprimento, mas sao pecas DIFERENTES - uma nao entra no lugar da
outra sem desdobrar e redobrar. Por isso a chave de comparacao inclui as
pernas da barra, lidas da coluna Dob./Reta/Dob. da tabela do projeto.

Posicoes marcadas "VAR." (comprimento variavel) NAO participam do
aproveitamento: sem medida fixa na tabela, nao da para garantir que duas
pecas sao iguais. Elas saem numa aba separada para conferencia manual.

O QUE ENTRA COMO ESTOQUE
------------------------
Por padrao, o trecho do pavimento de origem que NAO foi executado. O aco
do trecho executado ja virou estrutura - nao esta mais no canteiro.

Uso:
    python comparar_pavimentos.py
    python comparar_pavimentos.py --estoque "pasta" --demanda "pasta" \
        --trecho-estoque "TRECHO FT" --output resultado.xlsx
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import xlsxwriter

from extrator.config import carregar_config
from extrator.log_config import configurar_log, obter_log
from extrator.pipeline import processar

RAIZ = Path(__file__).resolve().parent


# =============================================================================
@dataclass
class Peca:
    """Um tipo de peca de corte e dobra: bitola + comprimento + dobras."""
    bitola_mm: float
    comprimento_cm: float
    pernas: tuple[float, ...]
    peso_linear: float = 0.0
    # de onde veio, para rastrear no projeto
    posicoes_estoque: set[str] = field(default_factory=set)
    posicoes_demanda: set[str] = field(default_factory=set)
    qtd_estoque: float = 0.0
    qtd_demanda: float = 0.0

    @property
    def chave(self) -> tuple:
        return (round(self.bitola_mm, 3), round(self.comprimento_cm, 1),
                tuple(round(x, 1) for x in self.pernas))

    @property
    def formato(self) -> str:
        if not self.pernas:
            return f"reta {self.comprimento_cm:g}"
        return " + ".join(f"{x:g}" for x in self.pernas)

    @property
    def qtd_aproveitada(self) -> float:
        return min(self.qtd_estoque, self.qtd_demanda)

    @property
    def qtd_a_comprar(self) -> float:
        return max(self.qtd_demanda - self.qtd_estoque, 0.0)

    @property
    def qtd_sobra(self) -> float:
        return max(self.qtd_estoque - self.qtd_demanda, 0.0)

    def peso(self, quantidade: float) -> float:
        return quantidade * self.comprimento_cm / 100.0 * self.peso_linear


# =============================================================================
def _formato_por_posicao(resultado) -> dict:
    """Liga cada linha do gabarito ao seu formato, por (prancha, pos, bitola).

    A tabela do projeto e por prancha, e o numero da posicao se repete
    entre pranchas - por isso a prancha entra na chave.
    """
    mapa = {}
    for prancha in resultado.pranchas:
        pass
    for linha in resultado.tabela_mestre:
        mapa.setdefault((linha.posicao, round(linha.bitola_mm, 3)), []).append(linha)
    return mapa


def coletar(pasta: Path, cfg, trechos_aceitos: set[str] | None,
            rotulo: str) -> tuple[dict, list, dict]:
    """Processa uma pasta e devolve (pecas, variaveis, estatisticas).

    `trechos_aceitos` filtra por trecho (ex.: so o TRECHO FT do estoque).
    None = considerar o pavimento inteiro.
    """
    log = obter_log()
    log.info("=" * 70)
    log.info("LENDO %s: %s", rotulo, pasta)
    resultado = processar(pasta, cfg)

    # --- formato de cada posicao, vindo do gabarito -------------------
    formatos: dict[tuple, object] = {}
    for linha in resultado.tabela_mestre:
        formatos[(linha.posicao, round(linha.bitola_mm, 3))] = linha

    # --- quantidade por posicao, filtrada por trecho ------------------
    quantidades: dict[tuple, float] = defaultdict(float)
    por_trecho: dict[str, float] = defaultdict(float)
    for p in resultado.posicoes:
        por_trecho[p.area] += p.peso_liquido_kg
        if trechos_aceitos is not None and p.area not in trechos_aceitos:
            continue
        quantidades[(p.posicao, round(p.bitola_mm, 3))] += p.quantidade

    # --- monta as pecas -----------------------------------------------
    pecas: dict[tuple, Peca] = {}
    variaveis: list[dict] = []
    sem_formato = 0

    for (pos, bitola), qtd in quantidades.items():
        linha = formatos.get((pos, bitola))
        if linha is None:
            sem_formato += 1
            continue
        if linha.variavel or not linha.comprimento_unitario_cm:
            variaveis.append({
                "posicao": pos, "bitola": bitola, "quantidade": qtd,
                "peso": qtd * linha.comprimento_total_cm / 100.0
                        * cfg.calculo.peso_linear_de(bitola) / max(linha.quantidade, 1)
                        if linha.quantidade else 0.0,
                "origem": rotulo,
            })
            continue

        peca = Peca(bitola_mm=bitola,
                    comprimento_cm=linha.comprimento_unitario_cm,
                    pernas=linha.pernas_cm,
                    peso_linear=cfg.calculo.peso_linear_de(bitola) or 0.0)
        alvo = pecas.setdefault(peca.chave, peca)
        if rotulo == "ESTOQUE":
            alvo.qtd_estoque += qtd
            alvo.posicoes_estoque.add(f"N{pos}")
        else:
            alvo.qtd_demanda += qtd
            alvo.posicoes_demanda.add(f"N{pos}")

    estat = {
        "arquivos": resultado.estatisticas.arquivos_lidos,
        "gabarito_kg": sum(l.peso_kg for l in resultado.tabela_mestre),
        "gabarito_linhas": len(resultado.tabela_mestre),
        "por_trecho": dict(por_trecho),
        "sem_formato": sem_formato,
        "trechos": sorted({a.nome for a in resultado.areas}),
    }
    log.info("  %s: %d pecas distintas, %d posicoes variaveis",
             rotulo, len(pecas), len(variaveis))
    return pecas, variaveis, estat


# =============================================================================
def cruzar(pecas_estoque: dict, pecas_demanda: dict) -> list[Peca]:
    """Junta os dois lados na mesma chave de peca."""
    todas: dict[tuple, Peca] = {}
    for chave, p in pecas_estoque.items():
        todas[chave] = p
    for chave, p in pecas_demanda.items():
        if chave in todas:
            alvo = todas[chave]
            alvo.qtd_demanda += p.qtd_demanda
            alvo.posicoes_demanda |= p.posicoes_demanda
        else:
            todas[chave] = p
    return sorted(todas.values(),
                  key=lambda p: (-p.peso(p.qtd_aproveitada), p.bitola_mm))


# =============================================================================
def exportar(pecas: list[Peca], variaveis: list[dict], est_e: dict,
             est_d: dict, cfg, destino: Path, nome_estoque: str,
             nome_demanda: str, trecho_estoque: str) -> Path:
    """Escreve o relatorio de aproveitamento."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(destino), {"nan_inf_to_errors": True})

    f_tit = wb.add_format({"bold": True, "font_size": 14, "font_color": "#FFFFFF",
                           "bg_color": "#1F4E78", "valign": "vcenter"})
    f_sub = wb.add_format({"italic": True, "font_size": 9, "font_color": "#444444",
                           "text_wrap": True, "valign": "top"})
    f_cab = wb.add_format({"bold": True, "font_color": "#FFFFFF",
                           "bg_color": "#1F4E78", "align": "center",
                           "text_wrap": True, "border": 1, "valign": "vcenter"})
    f_txt = wb.add_format({"border": 1})
    f_ctr = wb.add_format({"border": 1, "align": "center"})
    f_num = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "center"})
    f_kg = wb.add_format({"border": 1, "num_format": "#,##0.0"})
    f_kg_b = wb.add_format({"border": 1, "num_format": "#,##0.0", "bold": True,
                            "bg_color": "#DDEBF7"})
    f_tot = wb.add_format({"bold": True, "bg_color": "#1F4E78",
                           "font_color": "#FFFFFF", "border": 1,
                           "num_format": "#,##0.0"})
    f_tot_t = wb.add_format({"bold": True, "bg_color": "#1F4E78",
                             "font_color": "#FFFFFF", "border": 1})
    f_ok = wb.add_format({"bg_color": "#C6EFCE", "border": 1, "bold": True,
                          "num_format": "#,##0.0"})
    f_alerta = wb.add_format({"bg_color": "#FFEB9C", "border": 1,
                              "num_format": "#,##0.0"})

    kg_aprov = sum(p.peso(p.qtd_aproveitada) for p in pecas)
    kg_demanda = sum(p.peso(p.qtd_demanda) for p in pecas)
    kg_estoque = sum(p.peso(p.qtd_estoque) for p in pecas)
    kg_comprar = sum(p.peso(p.qtd_a_comprar) for p in pecas)
    kg_sobra = sum(p.peso(p.qtd_sobra) for p in pecas)

    # ================================================================== 1
    ws = wb.add_worksheet("RESUMO")
    ws.set_column(0, 0, 52)
    ws.set_column(1, 2, 18)
    ws.merge_range(0, 0, 0, 2, "APROVEITAMENTO DE ACO ENTRE PAVIMENTOS", f_tit)
    ws.set_row(0, 26)
    ws.merge_range(
        1, 0, 1, 2,
        f"Estoque: {nome_estoque} ({trecho_estoque})   |   "
        f"Demanda: {nome_demanda}   |   "
        f"Gerado em {_dt.datetime.now():%d/%m/%Y %H:%M}\n"
        "Uma peca so substitui outra com MESMA bitola, MESMO comprimento "
        "unitario e MESMO formato de dobras. Pesos em kg liquido (sem perda).",
        f_sub)
    ws.set_row(1, 42)

    linha = 3
    ws.write(linha, 0, "O QUE FOI COMPRADO E O QUE SOBROU", f_cab)
    ws.write(linha, 1, "kg", f_cab)
    ws.write(linha, 2, "% do comprado", f_cab)
    linha += 1
    comprado = est_e["gabarito_kg"]
    inteiro = "inteiro" in trecho_estoque.lower()
    # Com o pavimento inteiro como estoque nao existe "ja executado": a
    # diferenca para o comprado e so o que ficou fora da comparacao
    # (posicoes VAR. e sem formato identificado).
    if inteiro:
        blocos = [
            (f"Comprado - lista inteira do {nome_estoque}", comprado),
            ("Fora da comparacao (VAR. / sem formato na tabela)",
             comprado - kg_estoque),
            ("CONSIDERADO como estoque (pavimento inteiro)", kg_estoque),
        ]
    else:
        blocos = [
            (f"Comprado - lista inteira do {nome_estoque}", comprado),
            (f"Ja executado (fora do {trecho_estoque}) - aco consumido",
             comprado - kg_estoque),
            (f"DISPONIVEL no canteiro ({trecho_estoque})", kg_estoque),
        ]
    for rotulo, valor in blocos:
        ws.write(linha, 0, rotulo, f_txt)
        ws.write_number(linha, 1, valor, f_kg_b if ("DISPONIVEL" in rotulo or "CONSIDERADO" in rotulo) else f_kg)
        ws.write_number(linha, 2, valor / comprado if comprado else 0,
                        wb.add_format({"border": 1, "num_format": "0.0%",
                                       "align": "center"}))
        linha += 1

    linha += 1
    ws.write(linha, 0, f"NECESSIDADE DO {nome_demanda}", f_cab)
    ws.write(linha, 1, "kg", f_cab)
    ws.write(linha, 2, "% da demanda", f_cab)
    linha += 1
    for rotulo, valor, fmt in [
        ("Demanda total (peso com formato identificado)", kg_demanda, f_kg),
        ("APROVEITAVEL do estoque - nao precisa comprar", kg_aprov, f_ok),
        ("SALDO A COMPRAR", kg_comprar, f_alerta),
    ]:
        ws.write(linha, 0, rotulo, f_txt)
        ws.write_number(linha, 1, valor, fmt)
        ws.write_number(linha, 2, valor / kg_demanda if kg_demanda else 0,
                        wb.add_format({"border": 1, "num_format": "0.0%",
                                       "align": "center"}))
        linha += 1

    linha += 1
    ws.write(linha, 0, "SOBRA DO ESTOQUE SEM USO NESTE PAVIMENTO", f_tot_t)
    ws.write_number(linha, 1, kg_sobra, f_tot)
    linha += 2

    ws.write(linha, 0, "ECONOMIA", f_cab)
    ws.write(linha, 1, "", f_cab)
    ws.write(linha, 2, "", f_cab)
    linha += 1
    ws.write(linha, 0, "Aco que deixa de ser comprado", f_txt)
    ws.write_number(linha, 1, kg_aprov, f_ok)
    ws.write(linha, 2, "kg", f_ctr)
    linha += 2

    # --- o quanto a exigencia de dobras identicas custa ----------------
    # Numero que muda decisao: se ignorar as dobras dobra o aproveitamento,
    # vale negociar redobra com o fornecedor. Se nao muda, o problema e
    # que as lajes tem geometrias diferentes e nao ha o que fazer.
    por_comp = defaultdict(lambda: [0.0, 0.0])
    for pc in pecas:
        k = (round(pc.bitola_mm, 3), round(pc.comprimento_cm, 1))
        por_comp[k][0] += pc.peso(pc.qtd_estoque)
        por_comp[k][1] += pc.peso(pc.qtd_demanda)
    sem_dobra = sum(min(e, d) for e, d in por_comp.values())

    ws.write(linha, 0, "E SE AS DOBRAS NAO PRECISASSEM SER IGUAIS?", f_cab)
    ws.write(linha, 1, "kg", f_cab)
    ws.write(linha, 2, "% da demanda", f_cab)
    linha += 1
    pct = wb.add_format({"border": 1, "num_format": "0.0%", "align": "center"})
    for rotulo, valor, fmt in [
        ("Criterio adotado: bitola + comprimento + dobras identicas",
         kg_aprov, f_ok),
        ("Hipotese: mesma bitola e comprimento, dobras diferentes",
         sem_dobra, f_alerta),
        ("Ganho possivel se houvesse redobra das pecas",
         sem_dobra - kg_aprov, f_kg),
    ]:
        ws.write(linha, 0, rotulo, f_txt)
        ws.write_number(linha, 1, valor, fmt)
        ws.write_number(linha, 2, valor / kg_demanda if kg_demanda else 0, pct)
        linha += 1
    linha += 1

    # --- estoque x demanda por bitola ---------------------------------
    ws.write(linha, 0, "ONDE ESTA O DESENCONTRO - POR BITOLA", f_cab)
    ws.write(linha, 1, "estoque (kg)", f_cab)
    ws.write(linha, 2, "demanda (kg)", f_cab)
    linha += 1
    por_bitola = defaultdict(lambda: [0.0, 0.0])
    for pc in pecas:
        por_bitola[pc.bitola_mm][0] += pc.peso(pc.qtd_estoque)
        por_bitola[pc.bitola_mm][1] += pc.peso(pc.qtd_demanda)
    for bit in sorted(por_bitola):
        e, d = por_bitola[bit]
        ws.write(linha, 0, f"   Ø{bit:g} mm", f_txt)
        ws.write_number(linha, 1, e, f_kg)
        ws.write_number(linha, 2, d, f_kg)
        linha += 1
    linha += 1

    ws.merge_range(linha, 0, linha, 2,
                   "COMO LER: a aba APROVEITAMENTO lista peca a peca o que "
                   "pode sair do estoque. SALDO A COMPRAR e a lista de "
                   "compra corrigida. SOBRA lista o que continua parado no "
                   "canteiro. VARIAVEIS sao as posicoes sem medida fixa na "
                   "tabela do projeto - ficaram de fora da conta e precisam "
                   "de conferencia manual.", f_sub)
    ws.set_row(linha, 60)

    # ================================================================== 2
    def tabela(nome, filtro, coluna_qtd, titulo, ajuda):
        w = wb.add_worksheet(nome)
        w.set_column(0, 0, 11)
        w.set_column(1, 1, 15)
        w.set_column(2, 2, 26)
        w.set_column(3, 6, 15)
        w.set_column(7, 8, 26)
        w.merge_range(0, 0, 0, 8, titulo, f_tit)
        w.set_row(0, 24)
        w.merge_range(1, 0, 1, 8, ajuda, f_sub)
        w.set_row(1, 28)
        cabs = ["Bitola (mm)", "Comp. unit. (cm)", "Formato (dobras, cm)",
                "Qtd estoque", "Qtd demanda", coluna_qtd, "Peso (kg)",
                f"Posicoes {nome_estoque}", f"Posicoes {nome_demanda}"]
        for j, c in enumerate(cabs):
            w.write(3, j, c, f_cab)
        w.set_row(3, 30)
        L = 4
        total = 0.0
        for p in pecas:
            q = filtro(p)
            if q <= 0:
                continue
            kg = p.peso(q)
            total += kg
            w.write_number(L, 0, p.bitola_mm, f_ctr)
            w.write_number(L, 1, p.comprimento_cm, f_ctr)
            w.write(L, 2, p.formato, f_ctr)
            w.write_number(L, 3, p.qtd_estoque, f_num)
            w.write_number(L, 4, p.qtd_demanda, f_num)
            w.write_number(L, 5, q, f_num)
            w.write_number(L, 6, kg, f_kg)
            w.write(L, 7, ", ".join(sorted(p.posicoes_estoque)[:8]), f_txt)
            w.write(L, 8, ", ".join(sorted(p.posicoes_demanda)[:8]), f_txt)
            L += 1
        w.write(L, 0, "TOTAL", f_tot_t)
        for j in range(1, 6):
            w.write_blank(L, j, None, f_tot_t)
        w.write_number(L, 6, total, f_tot)
        w.write_blank(L, 7, None, f_tot_t)
        w.write_blank(L, 8, None, f_tot_t)
        w.freeze_panes(4, 3)
        w.autofilter(3, 0, max(L - 1, 4), 8)

    tabela("APROVEITAMENTO", lambda p: p.qtd_aproveitada, "Qtd APROVEITADA",
           "APROVEITAMENTO - PECAS DO ESTOQUE QUE SERVEM DIRETO",
           "Estas pecas ja estao cortadas e dobradas no canteiro e sao "
           "identicas as que o outro pavimento precisa. Nao precisam ser "
           "compradas nem retrabalhadas.")

    tabela("SALDO A COMPRAR", lambda p: p.qtd_a_comprar, "Qtd A COMPRAR",
           "SALDO A COMPRAR - O QUE O ESTOQUE NAO COBRE",
           "Lista de compra corrigida: o que o pavimento precisa e o "
           "estoque nao tem, ou tem em quantidade insuficiente.")

    tabela("SOBRA SEM USO", lambda p: p.qtd_sobra, "Qtd SOBRANDO",
           "SOBRA - ESTOQUE QUE NAO SERVE PARA ESTE PAVIMENTO",
           "Pecas que continuam paradas no canteiro: ou o formato nao se "
           "repete no outro pavimento, ou ha mais do que o necessario. "
           "Vale checar contra os demais pavimentos antes de sucatear.")

    # ================================================================== 3
    ws = wb.add_worksheet("VARIAVEIS")
    ws.set_column(0, 0, 16)
    ws.set_column(1, 4, 16)
    ws.merge_range(0, 0, 0, 4,
                   "POSICOES DE COMPRIMENTO VARIAVEL - FORA DA COMPARACAO", f_tit)
    ws.set_row(0, 24)
    ws.merge_range(
        1, 0, 1, 4,
        "A tabela do projeto marca estas posicoes como \"VAR.\": elas nao "
        "tem medida fixa, entao nao da para afirmar que duas pecas sao "
        "iguais. Ficaram FORA do aproveitamento e do saldo a comprar - "
        "confira uma a uma no projeto.", f_sub)
    ws.set_row(1, 32)
    for j, c in enumerate(["Origem", "Posicao", "Bitola (mm)", "Quantidade",
                           "Peso aprox. (kg)"]):
        ws.write(3, j, c, f_cab)
    L = 4
    total_var = 0.0
    for v in sorted(variaveis, key=lambda x: (x["origem"], x["bitola"])):
        ws.write(L, 0, v["origem"], f_ctr)
        ws.write(L, 1, f"N{v['posicao']}", f_ctr)
        ws.write_number(L, 2, v["bitola"], f_ctr)
        ws.write_number(L, 3, v["quantidade"], f_num)
        ws.write_number(L, 4, v["peso"], f_kg)
        total_var += v["peso"]
        L += 1
    ws.write(L, 0, "TOTAL", f_tot_t)
    for j in (1, 2, 3):
        ws.write_blank(L, j, None, f_tot_t)
    ws.write_number(L, 4, total_var, f_tot)
    ws.freeze_panes(4, 0)

    # ================================================================== 4
    ws = wb.add_worksheet("CONFERENCIA")
    ws.set_column(0, 0, 46)
    ws.set_column(1, 2, 20)
    ws.merge_range(0, 0, 0, 2, "CONFERENCIA DA LEITURA", f_tit)
    ws.set_row(0, 24)
    linha = 2
    for titulo, est, nome in [("ESTOQUE", est_e, nome_estoque),
                              ("DEMANDA", est_d, nome_demanda)]:
        ws.write(linha, 0, f"{titulo} - {nome}", f_cab)
        ws.write(linha, 1, "valor", f_cab)
        ws.write(linha, 2, "", f_cab)
        linha += 1
        for rotulo, valor in [
            ("Pranchas lidas", est["arquivos"]),
            ("Posicoes na tabela do projeto", est["gabarito_linhas"]),
            ("Peso total da tabela do projeto (kg)", round(est["gabarito_kg"], 1)),
            ("Trechos encontrados", ", ".join(est["trechos"])),
            ("Posicoes sem formato identificado", est["sem_formato"]),
        ]:
            ws.write(linha, 0, rotulo, f_txt)
            ws.write(linha, 1, valor, f_ctr)
            linha += 1
        ws.write(linha, 0, "Peso por trecho (kg)", f_cab)
        ws.write(linha, 1, "", f_cab)
        ws.write(linha, 2, "", f_cab)
        linha += 1
        for trecho, kg in sorted(est["por_trecho"].items(),
                                 key=lambda kv: -kv[1]):
            ws.write(linha, 0, f"   {trecho}", f_txt)
            ws.write_number(linha, 1, kg, f_kg)
            linha += 1
        linha += 1

    wb.close()
    return destino


# =============================================================================
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--estoque", default=r"C:\Users\nicol\Downloads\PILOTIS",
                   help="pasta com as pranchas do pavimento JA COMPRADO")
    p.add_argument("--demanda", default=r"C:\Users\nicol\Downloads\ACO LAJES\2PVTO",
                   help="pasta com as pranchas do pavimento a executar")
    p.add_argument("--trecho-estoque", default="TRECHO FT",
                   help="trecho do estoque que NAO foi executado e esta "
                        "disponivel no canteiro (vazio = pavimento inteiro)")
    p.add_argument("--nome-estoque", default="PILOTIS")
    p.add_argument("--nome-demanda", default="2o PAVIMENTO")
    p.add_argument("--config", default=str(RAIZ / "config.yaml"))
    p.add_argument("--output", "-o",
                   default=str(RAIZ / "saida" / "Aproveitamento de Aco.xlsx"))
    args = p.parse_args(argv)

    cfg = carregar_config(args.config)
    destino = Path(args.output)
    log = configurar_log(cfg.log, destino.parent)

    trechos = ({args.trecho_estoque} if args.trecho_estoque.strip() else None)

    pecas_e, var_e, est_e = coletar(Path(args.estoque), cfg, trechos, "ESTOQUE")
    pecas_d, var_d, est_d = coletar(Path(args.demanda), cfg, None, "DEMANDA")

    if trechos and not (set(trechos) & set(est_e["trechos"])):
        log.error("O trecho %r nao existe no estoque. Trechos encontrados: %s",
                  args.trecho_estoque, est_e["trechos"])
        return 2

    pecas = cruzar(pecas_e, pecas_d)
    caminho = exportar(pecas, var_e + var_d, est_e, est_d, cfg, destino,
                       args.nome_estoque, args.nome_demanda,
                       args.trecho_estoque or "pavimento inteiro")

    kg_aprov = sum(x.peso(x.qtd_aproveitada) for x in pecas)
    kg_dem = sum(x.peso(x.qtd_demanda) for x in pecas)
    log.info("=" * 70)
    log.info("APROVEITAMENTO")
    log.info("  pecas distintas cruzadas ..... %d", len(pecas))
    log.info("  demanda do %s ...... %.1f kg", args.nome_demanda, kg_dem)
    log.info("  aproveitavel do estoque ...... %.1f kg (%.1f%%)",
             kg_aprov, kg_aprov / kg_dem * 100 if kg_dem else 0)
    log.info("  saldo a comprar .............. %.1f kg", kg_dem - kg_aprov)
    log.info("  arquivo ...................... %s", caminho)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
