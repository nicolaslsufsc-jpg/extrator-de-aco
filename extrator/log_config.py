"""Configuracao do log: arquivo detalhado + console enxuto."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import LogCfg

NOME = "extrator_aco"


def configurar_log(cfg: LogCfg, pasta_saida: Path | None = None) -> logging.Logger:
    """Prepara o logger da aplicacao.

    O arquivo recebe tudo com carimbo de tempo (e o que sera consultado
    depois para auditar o processamento); o console recebe so a mensagem,
    para acompanhar a execucao.
    """
    logger = logging.getLogger(NOME)
    logger.setLevel(getattr(logging, cfg.nivel))
    logger.handlers.clear()
    logger.propagate = False

    caminho = Path(cfg.arquivo)
    if not caminho.is_absolute() and pasta_saida is not None:
        caminho = pasta_saida / caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(
        caminho, mode="w" if cfg.sobrescrever else "a", encoding="utf-8"
    )
    fh.setLevel(getattr(logging, cfg.nivel))
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    logger.debug("Log iniciado em %s", caminho)
    return logger


def obter_log() -> logging.Logger:
    return logging.getLogger(NOME)
