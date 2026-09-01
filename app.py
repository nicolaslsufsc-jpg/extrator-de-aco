"""
Extrator de Aco - interface de linha de comando.

Uso basico:
    python app.py --input pasta/ --output resultado.xlsx

Exemplos:
    python app.py --input "Prancha Exemplo Aco.dxf" --output quantitativo.xlsx
    python app.py --input pranchas/ --output obra.xlsx --config meu_config.yaml
    python app.py --input pranchas/ --output obra.xlsx --criterio proporcional
    python app.py --input pranchas/ --diagnostico
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from extrator.config import Config, carregar_config
from extrator.conversor import ConversorIndisponivel, localizar_oda
from extrator.exportacao import Exportador
from extrator.log_config import configurar_log
from extrator.pipeline import processar

RAIZ = Path(__file__).resolve().parent


# =============================================================================
def carregar_limites_externos(cfg: Config) -> None:
    """Le os limites por area de uma planilha, quando `arquivo_limites` existir.

    Formato esperado (xlsx ou csv), com cabecalho:
        area | bitola | limite_kg
    `bitola` vazia significa o limite TOTAL da area.
    """
    from extrator.config import LimiteArea
    from extrator.log_config import obter_log

    caminho = cfg.limites.arquivo_limites
    if not caminho:
        return
    p = Path(caminho)
    if not p.is_absolute():
        p = RAIZ / p
    log = obter_log()
    if not p.is_file():
        log.warning("limites.arquivo_limites nao encontrado: %s (ignorado)", p)
        return

    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    df.columns = [str(c).strip().lower() for c in df.columns]
    faltando = {"area", "limite_kg"} - set(df.columns)
    if faltando:
        log.error("planilha de limites sem a(s) coluna(s) %s; ignorada", faltando)
        return

    n = 0
    for _, r in df.iterrows():
        area = str(r["area"]).strip()
        if not area or area.lower() == "nan":
            continue
        try:
            limite = float(r["limite_kg"])
        except (TypeError, ValueError):
            continue
        alvo = cfg.limites.por_area.setdefault(area, LimiteArea())
        bitola = r.get("bitola")
        if bitola is None or (isinstance(bitola, float) and pd.isna(bitola)) \
                or str(bitola).strip() == "":
            alvo.total = limite
        else:
            alvo.por_bitola[float(str(bitola).replace(",", "."))] = limite
        n += 1
    log.info("Limites carregados de %s: %d linha(s)", p.name, n)


# =============================================================================
def nome_do_projeto(entrada: Path) -> str:
    """Nome do projeto a partir da entrada.

    Arquivo unico -> nome do arquivo sem extensao.
    Pasta         -> nome da pasta (e o que identifica a obra num lote).
    """
    p = Path(entrada)
    return (p.stem if p.is_file() else p.name).strip()


# =============================================================================
def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="app.py",
        description="Levantamento automatico de aco a partir de plantas de "
                    "armacao em DWG/DXF, separado por regioes da layer AREA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input", "-i", required=True,
                   help="arquivo DWG/DXF ou pasta com varias pranchas")
    p.add_argument("--output", "-o", default="quantitativo_aco.xlsx",
                   help="arquivo .xlsx de saida (padrao: quantitativo_aco.xlsx)")
    p.add_argument("--config", "-c", default=str(RAIZ / "config.yaml"),
                   help="caminho do config.yaml")
    p.add_argument("--projeto",
                   help="nome do projeto usado como prefixo das abas do Excel "
                        "(padrao: nome do arquivo, ou da pasta em lote)")
    p.add_argument("--criterio",
                   choices=["maior_parte", "centroide", "proporcional",
                            "fora_do_escopo"],
                   help="sobrescreve areas.criterio_divisa do config")
    p.add_argument("--perda", type=float,
                   help="sobrescreve o percentual de perda (ex.: 0.10 = 10%%)")
    p.add_argument("--log-nivel", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="sobrescreve log.nivel do config")
    p.add_argument("--limpo", action="store_true",
                   help="planilha enxuta: so as abas de trecho, RESUMO GERAL "
                        "e COMPARACAO FINAL. Mantem posicao e comprimento "
                        "unitario (corte e dobra); tira o detalhamento "
                        "linha-a-linha e as abas VERIFICACAO/INCONSISTENCIAS")
    p.add_argument("--sem-abas-area", action="store_true",
                   help="gera so o resumo geral, sem uma aba por area")
    p.add_argument("--diagnostico", action="store_true",
                   help="apenas le e relata; nao gera o Excel")
    p.add_argument("--checar-oda", action="store_true",
                   help="verifica se o ODA File Converter esta instalado e sai")
    return p


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)

    # --- configuracao ------------------------------------------------
    try:
        cfg = carregar_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERRO DE CONFIGURACAO\n{exc}", file=sys.stderr)
        return 2

    if args.log_nivel:
        cfg.log.nivel = args.log_nivel
    if args.criterio:
        cfg.areas.criterio_divisa = args.criterio
    if args.perda is not None:
        if not 0 <= args.perda <= 1:
            print("ERRO: --perda deve estar entre 0 e 1 (0.10 = 10%)",
                  file=sys.stderr)
            return 2
        cfg.calculo.perda_percentual = args.perda
    if args.limpo:
        cfg.saida.modo_limpo = True
    if args.sem_abas_area:
        cfg.saida.abas_por_area = False
    cfg.projeto = args.projeto or nome_do_projeto(Path(args.input))

    destino = Path(args.output)
    if not destino.is_absolute():
        destino = Path.cwd() / destino
    log = configurar_log(cfg.log, destino.parent)

    # --- checagem do conversor ---------------------------------------
    if args.checar_oda:
        exe = localizar_oda(cfg.conversao.caminho_oda)
        if exe:
            log.info("ODA File Converter encontrado: %s", exe)
            return 0
        from extrator.conversor import MENSAGEM_INSTALACAO
        log.error(MENSAGEM_INSTALACAO)
        return 1

    log.info("EXTRATOR DE ACO")
    log.info("entrada: %s", args.input)
    log.info("projeto: %s", cfg.projeto)
    log.info("config : %s", args.config)

    carregar_limites_externos(cfg)

    # --- pipeline ----------------------------------------------------
    try:
        resultado = processar(Path(args.input), cfg)
    except ConversorIndisponivel:
        return 1                     # a mensagem ja foi escrita no log
    except FileNotFoundError as exc:
        log.error("ERRO: %s", exc)
        return 2

    if not resultado.posicoes:
        log.error("Nenhuma posicao de armadura foi extraida. Verifique "
                  "layers.texto_armadura e parser.padroes no config.yaml, "
                  "e a aba INCONSISTENCIAS.")

    # --- saida -------------------------------------------------------
    if args.diagnostico:
        log.info("Modo diagnostico: Excel nao gerado.")
        return 0

    try:
        Exportador(cfg).exportar(resultado, destino)
    except PermissionError:
        log.error("ERRO: nao foi possivel gravar %s. O arquivo esta aberto "
                  "no Excel?", destino)
        return 3

    erros = sum(1 for i in resultado.inconsistencias
                if i.severidade.value == "ERRO")
    alertas = sum(1 for i in resultado.inconsistencias
                  if i.severidade.value == "ALERTA")
    if erros or alertas:
        log.warning("Confira a aba INCONSISTENCIAS: %d erro(s) e %d alerta(s).",
                    erros, alertas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
