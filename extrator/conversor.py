"""
Conversao DWG -> DXF pelo ODA File Converter.

O ezdxf nao le DWG. O ODA File Converter e gratuito e roda por linha de
comando. Este modulo localiza o executavel, converte em lote e mantem um
cache para nao reconverter o que ja foi convertido.

Sintaxe do ODA (posicional, sem flags):
    ODAFileConverter <pasta_entrada> <pasta_saida> <versao> <tipo>
                     <recursivo> <auditar> [filtro]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import ConversaoCfg
from .log_config import obter_log

# Locais onde o instalador do ODA costuma deixar o executavel no Windows.
PADROES_BUSCA = [
    r"C:\Program Files\ODA\*\ODAFileConverter.exe",
    r"C:\Program Files\ODA\*\*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
    r"C:\Program Files\Open Design Alliance\*\ODAFileConverter.exe",
]

MENSAGEM_INSTALACAO = """
--------------------------------------------------------------------------
ODA File Converter nao encontrado.

O ezdxf nao le arquivos DWG diretamente. Para processar DWG e preciso o
ODA File Converter (gratuito):

  1. Baixe em:  https://www.opendesign.com/guestfiles/oda_file_converter
     (escolha a versao Windows 64-bit; e necessario informar um e-mail)
  2. Instale com as opcoes padrao.
  3. Rode o programa de novo - o executavel e encontrado sozinho.

Se instalou em outro lugar, informe o caminho completo no config.yaml:

  conversao:
    caminho_oda: "D:/Programas/ODA/ODAFileConverter.exe"

ALTERNATIVA SEM INSTALAR NADA: exporte as pranchas como DXF pelo proprio
AutoCAD/Eberick (Salvar como -> DXF 2013 ou superior) e aponte o programa
para a pasta com os DXF. O restante do processamento e identico.
--------------------------------------------------------------------------
"""


class ConversorIndisponivel(RuntimeError):
    """O DWG precisa ser convertido, mas o conversor nao esta disponivel."""


def localizar_oda(caminho_config: str | None = None) -> Path | None:
    """Acha o ODAFileConverter.exe: config -> PATH -> pastas padrao."""
    log = obter_log()

    if caminho_config:
        p = Path(caminho_config)
        if p.is_file():
            return p
        log.warning("conversao.caminho_oda aponta para arquivo inexistente: %s", p)

    no_path = shutil.which("ODAFileConverter")
    if no_path:
        return Path(no_path)

    for padrao in PADROES_BUSCA:
        raiz = Path(padrao).anchor
        relativo = padrao[len(raiz):]
        try:
            achados = sorted(Path(raiz).glob(relativo))
        except OSError:
            continue
        if achados:
            # A ultima da ordem alfabetica costuma ser a versao mais nova.
            return achados[-1]
    return None


def _converter_pasta(exe: Path, entrada: Path, saida: Path, cfg: ConversaoCfg) -> None:
    """Executa o ODA para uma pasta inteira."""
    log = obter_log()
    saida.mkdir(parents=True, exist_ok=True)
    comando = [
        str(exe),
        str(entrada),
        str(saida),
        cfg.versao_saida,
        "DXF",
        "0",      # nao recursivo: o chamador controla quais pastas entram
        "1",      # auditar/corrigir o desenho na conversao
        "*.DWG",
    ]
    log.debug("ODA: %s", " ".join(comando))
    # O ODA abre uma janela mesmo em modo linha de comando; escondemos.
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        comando, capture_output=True, text=True,
        timeout=cfg.timeout_s, creationflags=flags,
    )
    if proc.returncode != 0:
        log.warning("ODA retornou codigo %s: %s", proc.returncode,
                    (proc.stderr or proc.stdout or "").strip()[:500])


def preparar_entradas(
    caminhos: list[Path], cfg: ConversaoCfg
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Devolve a lista de DXF prontos para leitura.

    DXF entram direto. DWG sao convertidos (respeitando o cache).
    Retorna (dxf_prontos, falhas) - falhas e uma lista de (arquivo, motivo).
    """
    log = obter_log()
    dxf: list[Path] = []
    dwg: list[Path] = []
    falhas: list[tuple[Path, str]] = []

    for c in caminhos:
        if c.suffix.lower() == ".dxf":
            dxf.append(c)
        elif c.suffix.lower() == ".dwg":
            dwg.append(c)

    if not dwg:
        return dxf, falhas

    exe = localizar_oda(cfg.caminho_oda)
    if exe is None:
        # Nao aborta o processamento: se houver DXF, segue com eles e
        # reporta os DWG que ficaram de fora.
        log.error(MENSAGEM_INSTALACAO)
        for d in dwg:
            falhas.append((d, "ODA File Converter nao encontrado"))
        if not dxf:
            raise ConversorIndisponivel(MENSAGEM_INSTALACAO)
        return dxf, falhas

    log.info("ODA File Converter: %s", exe)

    # Agrupa por pasta de origem: o ODA converte pasta inteira de uma vez,
    # o que e muito mais rapido do que chamar o executavel por arquivo.
    por_pasta: dict[Path, list[Path]] = {}
    for d in dwg:
        por_pasta.setdefault(d.parent, []).append(d)

    for pasta, arquivos in por_pasta.items():
        destino = Path(cfg.pasta_cache) if cfg.pasta_cache else pasta / "_dxf_convertido"

        pendentes = []
        for a in arquivos:
            alvo = destino / (a.stem + ".dxf")
            if (cfg.usar_cache and alvo.is_file()
                    and alvo.stat().st_mtime >= a.stat().st_mtime):
                log.info("  cache: %s", alvo.name)
                dxf.append(alvo)
            else:
                pendentes.append(a)

        if not pendentes:
            continue

        # O ODA converte a pasta toda. Se so alguns arquivos estao pendentes,
        # isola-os numa pasta temporaria para nao reconverter o resto.
        log.info("Convertendo %d DWG de %s", len(pendentes), pasta)
        if len(pendentes) == len(arquivos):
            _converter_pasta(exe, pasta, destino, cfg)
        else:
            with tempfile.TemporaryDirectory(prefix="extrator_aco_") as tmp:
                tmp_path = Path(tmp)
                for a in pendentes:
                    shutil.copy2(a, tmp_path / a.name)
                _converter_pasta(exe, tmp_path, destino, cfg)

        for a in pendentes:
            alvo = destino / (a.stem + ".dxf")
            if alvo.is_file():
                dxf.append(alvo)
                log.info("  convertido: %s", a.name)
            else:
                falhas.append((a, "conversao nao produziu DXF (arquivo corrompido "
                                  "ou com objetos proxy?)"))
                log.error("  FALHOU: %s", a.name)

    return dxf, falhas


def coletar_arquivos(entrada: Path) -> list[Path]:
    """Lista os DWG/DXF de um arquivo ou pasta (sem entrar no cache)."""
    if entrada.is_file():
        return [entrada]
    if not entrada.is_dir():
        raise FileNotFoundError(f"entrada nao encontrada: {entrada}")
    arquivos = [
        p for p in sorted(entrada.iterdir())
        if p.suffix.lower() in (".dwg", ".dxf") and p.parent.name != "_dxf_convertido"
    ]
    if not arquivos:
        raise FileNotFoundError(f"nenhum DWG/DXF em {entrada}")

    # Quando o mesmo desenho esta na pasta como .dwg E .dxf, o DXF ja e o
    # que seria produzido pela conversao. Levar os dois faria o aco contar
    # em dobro (ou, sem o ODA instalado, gerar um erro falso de conversao
    # para um arquivo que na verdade esta disponivel).
    dxf_disponivel = {p.stem.lower() for p in arquivos if p.suffix.lower() == ".dxf"}
    filtrados = [p for p in arquivos
                 if p.suffix.lower() == ".dxf" or p.stem.lower() not in dxf_disponivel]
    ignorados = len(arquivos) - len(filtrados)
    if ignorados:
        obter_log().info("%d arquivo(s) .dwg ignorados: o .dxf equivalente "
                         "ja esta na pasta", ignorados)
    return filtrados
