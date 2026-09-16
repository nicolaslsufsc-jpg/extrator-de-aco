"""
Leitura da TABELA MESTRE de aco desenhada na propria prancha.

O Eberick desenha o resumo de aco como uma grade de TEXTs soltos (1.852
celulas na prancha de exemplo). Este modulo remonta essa grade e devolve
uma linha por posicao, para que o quantitativo extraido das barras possa
ser confrontado com o que o projeto declara.

FORMATO ENCONTRADO (uma linha da tabela, com o X de cada celula):

    [270.1]3  [270.6]%%c6.3  [271.6]50  [272.5]9  [273.2]93  [274.1]9
    [274.9]111  [275.9]5550  [277.0]13.6
     pos       bitola        qtd        <- dobras/reta ->    comp   total  peso
                                                            unit    (cm)   (kg)

REGRA DE LEITURA - posicional DENTRO da linha, nunca por coordenada fixa:
    posicao          = celula imediatamente ANTES da bitola
    quantidade       = celula imediatamente DEPOIS da bitola
    peso (kg)        = ULTIMA celula da linha
    comprimento (cm) = PENULTIMA celula da linha

O numero de colunas do meio varia (dobra/reta/dobra aparecem ou nao, e ha
celulas "VAR."), por isso ancorar nas pontas e mais seguro que contar
colunas.

VALIDACAO FISICA - o que torna o parser confiavel:
    peso_declarado ~= (comprimento_cm / 100) * peso_linear(bitola)
Linha que nao fecha essa conta e descartada. Como as celulas do bloco de
totais a direita as vezes caem no mesmo Y de uma linha de posicao, o
parser vai APARANDO celulas do fim ate a conta fechar - e so entao aceita
a linha. Sem essa validacao, uma celula intrusa faria o peso ser lido
errado em silencio.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .config import Config
from .log_config import obter_log
from .modelos import TextoDXF

# Ate quantas celulas aparar do fim de uma linha tentando fechar a conta.
MAX_APARAS = 4


@dataclass(slots=True)
class LinhaMestre:
    """Uma posicao lida da tabela desenhada na prancha."""
    posicao: str
    bitola_mm: float
    quantidade: int
    comprimento_total_cm: float
    peso_kg: float
    # Diferenca relativa entre o peso declarado e o peso recalculado.
    erro_validacao: float = 0.0

    # --- FORMATO DA BARRA (corte e dobra) ---------------------------
    # As celulas do meio da tabela: Dob. | Reta | Dob. | Comp. unitario
    # A ULTIMA delas e o comprimento unitario; as anteriores sao as
    # pernas da barra. Duas barras de mesmo comprimento total podem ter
    # formatos diferentes (9+93+9 nao e 20+71+20) e NAO se substituem
    # numa lista de corte e dobra.
    pernas_cm: tuple[float, ...] = ()
    comprimento_unitario_cm: Optional[float] = None
    # As colunas Dob. | Reta | Dob. lidas DIRETO da tabela, cada celula
    # identificada pela coluna em que foi desenhada. Ficam None quando a
    # tabela nao traz cabecalho reconhecivel e o formato caiu no palpite.
    dobra_1_cm: Optional[float] = None
    reta_cm: Optional[float] = None
    dobra_2_cm: Optional[float] = None
    # True quando as tres acima vieram das colunas do cabecalho.
    formato_por_coluna: bool = False
    # True quando alguma celula do formato e "VAR." - barra de medida
    # variavel, que nao da para comparar com outra.
    variavel: bool = False
    # True quando a soma das pernas confere com o comprimento unitario.
    formato_conferido: bool = False
    # Prancha de onde esta linha foi lida. Preenchido pelo pipeline.
    # Num lote, cada prancha traz a SUA tabela e o `resultado.tabela_mestre`
    # junta todas: sem este campo, duas pranchas com a posicao N5 viram uma
    # chave so e a conferencia compara a barra de um desenho com a tabela
    # do outro, calada.
    prancha: str = ""

    @property
    def comprimento_total_m(self) -> float:
        return self.comprimento_total_cm / 100.0

    @property
    def chave_formato(self) -> tuple:
        """Identidade da peca para corte e dobra.

        Duas pecas com esta mesma chave sao intercambiaveis: mesma
        bitola, mesmo comprimento unitario e mesma sequencia de dobras.
        Barra variavel devolve chave vazia - nao serve para casar.
        """
        if self.variavel or self.comprimento_unitario_cm is None:
            return ()
        return (round(self.bitola_mm, 3),
                round(self.comprimento_unitario_cm, 1),
                tuple(round(x, 1) for x in self.pernas_cm))

    @property
    def dobra_reta_dobra(self) -> tuple:
        """Decompoe as pernas nas colunas Dobra 1 | Reta | Dobra 2.

        A RETA e sempre a perna MAIOR - e o corpo da barra; as dobras sao
        os ganchos das pontas, sempre menores. A ORDEM em que aparecem na
        tabela diz de que lado esta o gancho:

            "400"           -> reta 400, sem dobra
            "19 + 391"      -> dobra 19 na ponta de entrada, reta 391
            "391 + 19"      -> reta 391, dobra 19 na ponta de saida
            "9 + 93 + 9"    -> dobra 9, reta 93, dobra 9

        Nos projetos analisados o maximo sao 3 pernas (2 dobras). Se
        aparecer mais, as pernas extras entram na coluna da reta somadas,
        e o comprimento total continua correto.

        QUANDO A TABELA TEM CABECALHO, NADA DISSO E USADO: as tres
        colunas sao lidas direto do desenho e devolvidas como estao. A
        heuristica abaixo so vale para tabela sem cabecalho legivel.
        """
        if self.formato_por_coluna:
            return (self.dobra_1_cm, self.reta_cm, self.dobra_2_cm)
        p = self.pernas_cm
        if not p:
            return (None, self.comprimento_unitario_cm, None)
        if len(p) == 1:
            return (None, p[0], None)
        if len(p) == 2:
            # A maior e a reta; a ordem diz de que lado fica o gancho.
            return (p[0], p[1], None) if p[0] < p[1] else (None, p[0], p[1])
        return (p[0], sum(p[1:-1]), p[-1])

    @property
    def formato_texto(self) -> str:
        """Formato legivel: "9 + 93 + 9" ou "reta 1200"."""
        if self.variavel:
            return "VAR."
        if not self.pernas_cm:
            return (f"reta {self.comprimento_unitario_cm:g}"
                    if self.comprimento_unitario_cm else "-")
        return " + ".join(f"{x:g}" for x in self.pernas_cm)


class LeitorTabelaMestre:
    """Remonta a grade de textos da tabela e valida cada linha."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.log = obter_log()
        # Aceita "%%c10", "Ø10", "O10" ja normalizados pelo parser de texto.
        self._rx_bitola = re.compile(r"^[Ø#]?\s*(\d+(?:[.,]\d+)?)\s*$")

    # ------------------------------------------------------------------
    def ler(self, textos: list[TextoDXF],
            normalizar) -> tuple[list[LinhaMestre], list[str]]:
        """Devolve (linhas_validas, avisos).

        `normalizar` e a funcao do parser que troca %%c por Ø - reusada
        aqui para nao duplicar a tabela de substituicoes do config.
        """
        avisos: list[str] = []
        if not textos:
            return [], ["nenhum texto encontrado nas layers da tabela mestre"]

        # --- agrupa as celulas em linhas pelo Y ------------------------
        alturas = [t.altura for t in textos if t.altura > 0]
        tol_y = (sorted(alturas)[len(alturas) // 2] * 0.3) if alturas else 0.05

        celulas = sorted(
            ((t.y, t.x, normalizar(t.conteudo).strip()) for t in textos),
            key=lambda c: (-c[0], c[1]),
        )
        linhas: list[list[tuple[float, str]]] = []
        atual: list[tuple[float, str]] = []
        y_ref: Optional[float] = None
        for y, x, texto in celulas:
            if not texto:
                continue
            if y_ref is None or abs(y - y_ref) <= tol_y:
                y_ref = y if y_ref is None else y_ref
                atual.append((x, texto))
            else:
                linhas.append(sorted(atual))
                atual = [(x, texto)]
                y_ref = y
        if atual:
            linhas.append(sorted(atual))

        # --- onde ficam as colunas Dob. | Reta | Dob. | Comp. ----------
        # Sem isso o formato da barra vira palpite ("a maior perna e a
        # reta"). Com isso, cada celula e lida na coluna em que o
        # projetista a desenhou.
        ancoras = self._ancoras_do_cabecalho(linhas)
        if ancoras:
            self.log.info("  colunas do formato localizadas no cabecalho: "
                          "%s", ", ".join(f"{k}@{v:.2f}"
                                          for k, v in sorted(ancoras.items(),
                                                             key=lambda kv: kv[1])))
        else:
            avisos.append(
                "cabecalho da tabela mestre nao encontrado (colunas 'Reta' "
                "e 'Comp.'); as dobras foram deduzidas pelo tamanho das "
                "pernas e podem sair trocadas de lado")

        # --- interpreta linha a linha ----------------------------------
        validas: list[LinhaMestre] = []
        descartadas = 0
        for linha in linhas:
            resultado = self._interpretar_linha(linha, ancoras)
            if resultado is None:
                if self._parece_linha_de_posicao([t for _, t in linha]):
                    descartadas += 1
                continue
            validas.append(resultado)

        if descartadas:
            avisos.append(
                f"{descartadas} linha(s) da tabela mestre tinham cara de "
                f"posicao mas nao fecharam a conta peso x comprimento; foram "
                f"ignoradas para nao entrar numero errado na comparacao")

        self.log.info("  tabela mestre do desenho: %d linha(s) lidas, "
                      "%d descartadas", len(validas), descartadas)
        return validas, avisos

    # ------------------------------------------------------------------
    def _ancoras_do_cabecalho(
        self, linhas: list[list[tuple[float, str]]],
    ) -> dict[str, float]:
        """Acha o X das colunas Dob. | Reta | Dob. | Comp. no cabecalho.

        O cabecalho da tabela do Eberick e:

            Elemento | Pos. | Diam. | Q. | Dob. | Reta | Dob. | Comp. | ...
                                          (cm)   (cm)   (cm)   (cm)

        As celulas vazias NAO existem como texto no DXF - uma barra reta
        simplesmente nao tem a celula "Dob.". Por isso contar celulas da
        esquerda para a direita nao diz em que coluna cada numero esta; o
        X diz. Como o texto da tabela e alinhado, o `align_point` de toda
        a coluna e o mesmo, e a leitura fica exata.

        A ancora e o proprio rotulo do cabecalho. Devolve {} quando nao
        houver cabecalho reconhecivel - ai o formato cai na heuristica.
        """
        def limpo(t: str) -> str:
            return t.strip().lower().rstrip(".")

        for linha in linhas:
            rotulos = [(x, limpo(t)) for x, t in linha]
            x_reta = next((x for x, t in rotulos if t == "reta"), None)
            if x_reta is None:
                continue
            x_comp = min((x for x, t in rotulos
                          if t in ("comp", "comprimento") and x > x_reta),
                         default=None)
            if x_comp is None:
                continue

            dobras = sorted(x for x, t in rotulos if t in ("dob", "dobra"))
            antes = [x for x in dobras if x < x_reta]
            depois = [x for x in dobras if x_reta < x < x_comp]

            ancoras = {"reta": x_reta, "comprimento": x_comp}
            if antes:
                ancoras["dobra_1"] = max(antes)     # a colada na Reta
            if depois:
                ancoras["dobra_2"] = min(depois)
            return ancoras
        return {}

    # ------------------------------------------------------------------
    def _numero(self, texto: str) -> Optional[float]:
        t = texto.strip().replace(",", ".")
        if not re.fullmatch(r"\d+(?:\.\d+)?", t):
            return None
        return float(t)

    def _bitola(self, texto: str) -> Optional[float]:
        """Reconhece a celula de bitola: precisa ter vindo de um Ø."""
        t = texto.strip()
        if not t.startswith(("Ø", "#")):
            return None
        m = self._rx_bitola.match(t)
        if not m:
            return None
        valor = float(m.group(1).replace(",", "."))
        return valor if valor in self.cfg.calculo.peso_linear else None

    def _parece_linha_de_posicao(self, celulas: list[str]) -> bool:
        return len(celulas) >= 4 and any(self._bitola(c) for c in celulas)

    # ------------------------------------------------------------------
    def _interpretar_linha(
        self, celulas_xy: list[tuple[float, str]],
        ancoras: dict[str, float],
    ) -> Optional[LinhaMestre]:
        """Aplica a regra posicional e so aceita se a fisica fechar.

        Posicao, bitola, quantidade, comprimento total e peso saem da
        ordem das celulas, conferida pela fisica (peso x comprimento). O
        FORMATO (dobras) sai das colunas - ver `_preencher_formato`.
        """
        celulas = [t for _, t in celulas_xy]
        idx_bit = next((i for i, c in enumerate(celulas) if self._bitola(c)), None)
        if idx_bit is None or idx_bit == 0 or idx_bit + 1 >= len(celulas):
            return None

        bitola = self._bitola(celulas[idx_bit])
        peso_linear = self.cfg.calculo.peso_linear_de(bitola)
        if not peso_linear:
            return None

        posicao = celulas[idx_bit - 1].strip()
        if not re.fullmatch(r"\d+[A-Za-z]?", posicao):
            return None
        quantidade = self._numero(celulas[idx_bit + 1])
        if quantidade is None or quantidade <= 0:
            return None

        # Apara celulas do fim ate peso e comprimento fecharem a conta.
        tol = self.cfg.tabela_mestre.tolerancia_validacao
        for corte in range(MAX_APARAS + 1):
            fim = len(celulas) - corte
            if fim < idx_bit + 3:
                break
            peso = self._numero(celulas[fim - 1])
            comprimento = self._numero(celulas[fim - 2])
            if peso is None or comprimento is None or peso <= 0 or comprimento <= 0:
                continue
            esperado = (comprimento / 100.0) * peso_linear
            if esperado <= 0:
                continue
            erro = abs(peso - esperado) / esperado
            if erro <= tol:
                linha = LinhaMestre(
                    posicao=posicao, bitola_mm=bitola,
                    quantidade=int(quantidade),
                    comprimento_total_cm=comprimento, peso_kg=peso,
                    erro_validacao=erro,
                )
                self._preencher_formato(
                    linha, celulas_xy[idx_bit + 2:fim - 2], ancoras)
                return linha
        return None

    # ------------------------------------------------------------------
    def _preencher_formato(
        self, linha: LinhaMestre, meio: list[tuple[float, str]],
        ancoras: dict[str, float],
    ) -> None:
        """Le as colunas Dob. | Reta | Dob. | Comp. unitario.

        Havendo cabecalho, cada celula vai para a coluna cujo X esta mais
        perto do seu - e a tabela quem diz de que lado esta cada gancho.
        Sem cabecalho, cai na regra antiga: a ultima celula e o
        comprimento unitario e as anteriores sao as pernas, em ordem.

        Nos dois casos a leitura so e dada por conferida quando
        Dob. + Reta + Dob. bate com o comprimento unitario. E essa soma
        que denuncia leitura deslocada uma coluna para o lado.
        """
        valores = [self._numero(c) for _, c in meio]
        linha.variavel = any(v is None for v in valores) or not valores

        if linha.variavel:
            # Sem medida fixa ("VAR."): nao da para comparar com outra peca.
            linha.comprimento_unitario_cm = None
            linha.pernas_cm = ()
            return

        if ancoras:
            self._formato_por_coluna(linha, meio, ancoras)
        else:
            linha.comprimento_unitario_cm = valores[-1]
            linha.pernas_cm = tuple(valores[:-1])

        comp = linha.comprimento_unitario_cm
        if linha.pernas_cm and comp:
            soma = sum(linha.pernas_cm)
            linha.formato_conferido = (
                abs(soma - comp) <= max(1.0, 0.02 * comp))
        else:
            # Barra reta: uma celula so, o proprio comprimento.
            linha.formato_conferido = True

    # ------------------------------------------------------------------
    def _formato_por_coluna(
        self, linha: LinhaMestre, meio: list[tuple[float, str]],
        ancoras: dict[str, float],
    ) -> None:
        """Cada celula na coluna em que foi desenhada."""
        achado: dict[str, float] = {}
        for x, texto in meio:
            coluna = min(ancoras, key=lambda c: abs(x - ancoras[c]))
            valor = self._numero(texto)
            if valor is None:
                continue
            # Duas celulas na mesma coluna significa que a linha nao tem
            # a forma esperada; soma para nao perder comprimento.
            achado[coluna] = achado.get(coluna, 0.0) + valor

        linha.dobra_1_cm = achado.get("dobra_1")
        linha.reta_cm = achado.get("reta")
        linha.dobra_2_cm = achado.get("dobra_2")
        linha.comprimento_unitario_cm = achado.get("comprimento")
        linha.formato_por_coluna = True
        linha.pernas_cm = tuple(
            v for v in (linha.dobra_1_cm, linha.reta_cm, linha.dobra_2_cm)
            if v is not None)


# =============================================================================
def totais_por_bitola(linhas: list[LinhaMestre]) -> dict[float, dict[str, float]]:
    """Agrega a tabela mestre por bitola."""
    agregado: dict[float, dict[str, float]] = {}
    for l in linhas:
        alvo = agregado.setdefault(
            l.bitola_mm, {"comprimento_m": 0.0, "peso_kg": 0.0, "posicoes": 0})
        alvo["comprimento_m"] += l.comprimento_total_m
        alvo["peso_kg"] += l.peso_kg
        alvo["posicoes"] += 1
    return dict(sorted(agregado.items()))
