"""
Quantidade de barras a partir da linha de distribuicao.

O PROBLEMA
----------
Uma armadura distribuida costuma vir escrita SEM quantidade:

    N3-Ø8c/10 C=300

O texto diz o espacamento (c/10) e o comprimento (C=300), mas nao quantas
barras sao. Lido ao pe da letra, isso vira 1 barra - e o quantitativo sai
10 a 25 vezes menor do que o real.

ONDE ESTA A QUANTIDADE
----------------------
Na EXTENSAO da distribuicao, desenhada como um numero solto na layer de
distribuicao (ARR_*_IG_DIST no padrao Eberick), ao lado da barra:

    extensao 200 cm  /  espacamento 10 cm  ->  20 barras

A conta e `ceil(extensao / espacamento)`, conferida na prancha de exemplo:

    N1: 2375 / 15 -> 159  (a tabela do projeto diz 159)
    N5:  350 / 10 ->  35  (a tabela diz 35)
    N7:  375 / 10 ->  38  (a tabela diz 38)
    N3:  275 / 11 ->  25  (a tabela diz 25)

QUANDO ISTO E USADO
-------------------
So para posicao cuja quantidade NAO estava escrita no texto. Texto com
quantidade explicita ("N264-1Ø10 C=790") manda, sempre.

O RISCO, dito com todas as letras
---------------------------------
E preciso decidir qual numero de extensao pertence a qual barra, e isso e
feito por proximidade. Onde ha duas extensoes quase a mesma distancia, a
escolha pode errar - esses casos sao reportados em INCONSISTENCIAS em vez
de passarem calados.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from .config import Config, casa_padrao
from .log_config import obter_log
from .modelos import (Inconsistencia, PosicaoArmadura, ResultadoProcessamento,
                      Severidade, TextoDXF, TipoInconsistencia)

_SO_NUMERO = re.compile(r"^\d+(?:[.,]\d+)?$")


def coletar_extensoes(textos: list[TextoDXF],
                      cfg: Config) -> list[tuple[float, float, float]]:
    """Devolve [(x, y, extensao_cm)] dos rotulos de distribuicao.

    Sao textos puramente numericos nas layers de distribuicao. O valor
    esta em centimetros reais (nao em unidades de desenho).
    """
    achados: list[tuple[float, float, float]] = []
    for t in textos:
        if not casa_padrao(t.layer, cfg.layers.texto_distribuicao):
            continue
        bruto = t.conteudo.strip().replace(",", ".")
        if not _SO_NUMERO.match(bruto):
            continue
        valor = float(bruto)
        if valor <= 0:
            continue
        achados.append((t.x, t.y, valor))
    return achados


def recuperar_quantidades(
    posicoes: list[PosicaoArmadura],
    extensoes: list[tuple[float, float, float]],
    cfg: Config, prancha: str, resultado: ResultadoProcessamento,
) -> None:
    """Preenche a quantidade das barras distribuidas sem quantidade escrita."""
    log = obter_log()
    if not cfg.calculo.recuperar_quantidade_distribuicao:
        return

    alvos = [p for p in posicoes
             if not p.quantidade_explicita and p.espacamento_cm
             and p.espacamento_cm > 0]
    if not alvos:
        return
    if not extensoes:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.DISTRIBUICAO_SEM_EXTENSAO, Severidade.ALERTA,
            f"{len(alvos)} posicao(oes) trazem espacamento mas nao a "
            f"quantidade, e nenhum rotulo de extensao foi encontrado nas "
            f"layers {', '.join(cfg.layers.texto_distribuicao)}. Cada uma "
            f"esta contando como 1 barra - o quantitativo esta MENOR que o "
            f"real. Confira se essas layers existem no desenho",
            prancha=prancha, ocorrencias=len(alvos)))
        return

    raio = cfg.raio_associacao * cfg.calculo.raio_extensao_fator
    recuperadas = ambiguas = sem_extensao = 0

    for p in alvos:
        # Distancia medida a partir do texto da posicao: o rotulo da
        # extensao e escrito ao lado da barra que ele mede.
        candidatos = sorted(
            ((math.dist((p.x_texto, p.y_texto), (x, y)), valor)
             for x, y, valor in extensoes),
            key=lambda c: c[0],
        )
        if not candidatos or candidatos[0][0] > raio:
            sem_extensao += 1
            continue

        dist, extensao = candidatos[0]
        quantidade = math.ceil(extensao / p.espacamento_cm)
        if quantidade <= 0:
            sem_extensao += 1
            continue

        # Ambiguidade: dois rotulos praticamente a mesma distancia e com
        # valores diferentes. A escolha pode ter errado de barra.
        if len(candidatos) > 1:
            d2, v2 = candidatos[1]
            if v2 != extensao and d2 <= dist * (1 + cfg.calculo.margem_ambiguidade):
                ambiguas += 1
                resultado.adicionar(Inconsistencia(
                    TipoInconsistencia.DISTRIBUICAO_AMBIGUA, Severidade.ALERTA,
                    f"N{p.posicao}: ha dois rotulos de extensao quase a mesma "
                    f"distancia ({extensao:.0f} cm a {dist:.2f} e {v2:.0f} cm "
                    f"a {d2:.2f}). Foi adotado {extensao:.0f} cm -> "
                    f"{quantidade} barras. Confira no CAD",
                    prancha=prancha, layer=p.layer_texto,
                    handle=p.handle_texto, texto=p.texto_origem,
                    x=p.x_texto, y=p.y_texto))

        p.quantidade = float(quantidade)
        p.quantidade_desenho = float(quantidade)
        p.extensao_distribuicao_cm = extensao
        p.origem_quantidade = "distribuicao"
        recuperadas += 1

    if sem_extensao:
        resultado.adicionar(Inconsistencia(
            TipoInconsistencia.DISTRIBUICAO_SEM_EXTENSAO, Severidade.ALERTA,
            f"{sem_extensao} posicao(oes) com espacamento nao acharam rotulo "
            f"de extensao dentro do raio de busca; continuam contando 1 barra "
            f"e estao SUBCONTADAS no quantitativo",
            prancha=prancha, ocorrencias=sem_extensao))

    log.info("  quantidade pela distribuicao: %d recuperada(s), "
             "%d ambigua(s), %d sem rotulo", recuperadas, ambiguas,
             sem_extensao)
