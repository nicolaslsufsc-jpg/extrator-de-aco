"""
Agrupamento de textos empilhados.

E comum duas ou tres posicoes serem escritas lado a lado ou empilhadas no
mesmo ponto, referindo-se a barras sobrepostas. O programa precisa
trata-las como POSICOES DISTINTAS - e nao como um unico texto quebrado.

O agrupamento serve a dois propositos:
  1. impedir que varias posicoes vizinhas disputem a mesma barra: dentro de
     um grupo a atribuicao e exclusiva (ver associacao.py);
  2. permitir remontar um texto que o CAD quebrou em dois pedacos, quando
     nenhum dos pedacos e interpretavel sozinho.

O agrupamento usa GRID HASHING (celula = tolerancia): cada texto so e
comparado com os vizinhos das 9 celulas ao redor. Custo linear, nao O(n^2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .config import Config
from .modelos import TextoDXF


@dataclass(slots=True)
class GrupoTextos:
    """Textos que ocupam praticamente o mesmo ponto do desenho."""
    indices: list[int] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0


def agrupar(textos: list[TextoDXF], cfg: Config) -> list[GrupoTextos]:
    """Agrupa por proximidade usando union-find sobre uma grade espacial."""
    tol = cfg.tol_agrupamento
    n = len(textos)
    if n == 0:
        return []
    if tol <= 0:
        return [GrupoTextos([i], textos[i].x, textos[i].y) for i in range(n)]

    # --- grade: chave (col, lin) -> indices dos textos naquela celula ---
    grade: dict[tuple[int, int], list[int]] = {}
    for i, t in enumerate(textos):
        chave = (int(t.x // tol), int(t.y // tol))
        grade.setdefault(chave, []).append(i)

    pai = list(range(n))

    def raiz(a: int) -> int:
        while pai[a] != a:
            pai[a] = pai[pai[a]]        # compressao de caminho
            a = pai[a]
        return a

    def unir(a: int, b: int) -> None:
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            pai[rb] = ra

    tol2 = tol * tol
    for (cx, cy), indices in grade.items():
        # Vizinhanca 3x3: qualquer par a menos de `tol` cai em celulas
        # adjacentes, entao nenhuma comparacao util e perdida.
        vizinhos: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                vizinhos.extend(grade.get((cx + dx, cy + dy), ()))
        for i in indices:
            ti = textos[i]
            for j in vizinhos:
                if j <= i:
                    continue
                tj = textos[j]
                if (ti.x - tj.x) ** 2 + (ti.y - tj.y) ** 2 <= tol2:
                    unir(i, j)

    agrupados: dict[int, list[int]] = {}
    for i in range(n):
        agrupados.setdefault(raiz(i), []).append(i)

    grupos: list[GrupoTextos] = []
    for indices in agrupados.values():
        indices.sort(key=lambda k: (-textos[k].y, textos[k].x))   # de cima para baixo
        gx = sum(textos[k].x for k in indices) / len(indices)
        gy = sum(textos[k].y for k in indices) / len(indices)
        grupos.append(GrupoTextos(indices, gx, gy))
    return grupos


def remontar_fragmentos(
    grupo: GrupoTextos, textos: list[TextoDXF], nao_interpretados: set[int],
    tenta_interpretar,
) -> list[tuple[int, int, str]]:
    """Tenta juntar pedacos vizinhos que sozinhos nao foram interpretados.

    Recebe `tenta_interpretar(texto) -> bool` e devolve a lista de junções
    bem sucedidas como (indice_a, indice_b, texto_juntado).

    So junta pares em que PELO MENOS UM dos lados falhou sozinho: assim duas
    posicoes empilhadas validas nunca sao coladas uma na outra por engano.
    """
    juncoes: list[tuple[int, int, str]] = []
    ordenados = grupo.indices
    usados: set[int] = set()

    for a, b in zip(ordenados, ordenados[1:]):
        if a in usados or b in usados:
            continue
        if a not in nao_interpretados and b not in nao_interpretados:
            continue
        for junto in (f"{textos[a].conteudo} {textos[b].conteudo}",
                      f"{textos[a].conteudo}{textos[b].conteudo}"):
            if tenta_interpretar(junto):
                juncoes.append((a, b, junto))
                usados.update((a, b))
                break
    return juncoes


def estatisticas_grupos(grupos: Iterable[GrupoTextos]) -> dict[int, int]:
    """Distribuicao do tamanho dos grupos (para o log)."""
    dist: dict[int, int] = {}
    for g in grupos:
        dist[len(g.indices)] = dist.get(len(g.indices), 0) + 1
    return dict(sorted(dist.items()))
