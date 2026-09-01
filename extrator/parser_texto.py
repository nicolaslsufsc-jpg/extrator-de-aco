"""
Parser dos textos de armadura.

Transforma  "159N1-%%c10c/15 C=880-900"  em numeros, usando exclusivamente
as regex declaradas no config.yaml. Nenhum formato esta embutido no codigo.

Regra de ouro deste modulo: texto que nao for entendido NAO desaparece.
Ou casa com `ignorar_textos` (ruido conhecido, apenas contado), ou volta
como problema para ir parar na aba INCONSISTENCIAS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .config import Config
from .modelos import PosicaoBruta, Severidade, TipoInconsistencia


@dataclass(slots=True)
class ProblemaParser:
    """Problema encontrado ao interpretar um texto."""
    tipo: TipoInconsistencia
    severidade: Severidade
    descricao: str


@dataclass(slots=True)
class ResultadoParser:
    """Saida do parser para UM texto.

    Um unico texto pode gerar varias posicoes (formato "A+B") e varios
    problemas ao mesmo tempo (ex.: interpretou, mas o comprimento e variavel).
    """
    posicoes: list[PosicaoBruta]
    problemas: list[ProblemaParser]
    # True quando o texto casou com `ignorar_textos`: nao e erro, e ruido.
    ignorado: bool = False


class ParserArmadura:
    """Compila as regex do config uma unica vez e interpreta textos em lote."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        p = cfg.parser
        # Compila tudo no construtor: o parser roda milhares de vezes.
        self._padroes = [(pd.nome, re.compile(pd.regex)) for pd in p.padroes]
        self._ignorar = [re.compile(r) for r in p.ignorar_textos]
        # Substituicoes ordenadas da chave mais longa para a mais curta,
        # para "%%%" nao ser comido por "%%c".
        self._subs = sorted(p.substituicoes.items(), key=lambda kv: -len(kv[0]))
        self._bitolas = sorted(p.bitolas_validas)

    # ------------------------------------------------------------------
    # Normalizacao
    # ------------------------------------------------------------------
    def normalizar(self, texto: str) -> str:
        """Troca codigos de controle do AutoCAD e limpa espacos.

        `%%c` e `%%C` sao a forma como o Eberick grava o simbolo de diametro.
        Sem esta troca nenhuma regex casaria.
        """
        t = texto
        for de, para in self._subs:
            t = t.replace(de, para)
        # Remove formatacao de MTEXT que tenha sobrado (\P, \pxi, {\f...})
        t = re.sub(r"\\[Pp]", " ", t)
        t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t)
        t = t.replace("{", "").replace("}", "")
        # Espacos multiplos e nao-quebraveis viram um espaco simples.
        t = re.sub(r"[\s ]+", " ", t)
        return t.strip()

    def _numero(self, bruto: str) -> float:
        """Converte "12,5" ou "12.5" em float conforme a configuracao."""
        s = bruto.strip()
        if self.cfg.parser.decimal_virgula:
            s = s.replace(",", ".")
        return float(s)

    # ------------------------------------------------------------------
    # Bitola
    # ------------------------------------------------------------------
    def _ajustar_bitola(self, valor: float) -> tuple[float, Optional[ProblemaParser]]:
        """Valida a bitola contra a lista da NBR e arredonda se estiver perto.

        Devolve (bitola_ajustada, problema_ou_None). Uma bitola desconhecida
        NAO e descartada: entra no quantitativo e vira alerta, porque
        descartar em silencio seria pior.
        """
        if valor in self._bitolas:
            return valor, None
        tol = self.cfg.parser.tolerancia_bitola
        if tol > 0:
            maisproxima = min(self._bitolas, key=lambda b: abs(b - valor))
            if abs(maisproxima - valor) <= tol:
                return maisproxima, None
        return valor, ProblemaParser(
            TipoInconsistencia.BITOLA_INVALIDA,
            Severidade.ALERTA,
            f"bitola {valor} mm nao consta em parser.bitolas_validas",
        )

    # ------------------------------------------------------------------
    # Interpretacao de um trecho ja separado (sem "+")
    # ------------------------------------------------------------------
    def _interpretar_trecho(self, trecho: str) -> tuple[Optional[PosicaoBruta], list[ProblemaParser]]:
        problemas: list[ProblemaParser] = []
        for nome, rx in self._padroes:
            m = rx.match(trecho)
            if not m:
                continue
            g = m.groupdict()

            # --- quantidade ------------------------------------------------
            bruto_qtd = g.get("quantidade")
            quantidade = (int(self._numero(bruto_qtd)) if bruto_qtd
                          else self.cfg.parser.quantidade_padrao)
            # Guardar se o numero veio do texto ou foi assumido: e o que
            # permite recuperar depois a quantidade pela distribuicao.
            quantidade_explicita = bruto_qtd is not None
            if quantidade <= 0:
                problemas.append(ProblemaParser(
                    TipoInconsistencia.TEXTO_NAO_INTERPRETADO, Severidade.ERRO,
                    f"quantidade invalida ({quantidade})"))
                return None, problemas

            # --- bitola ----------------------------------------------------
            bitola = self._numero(g["bitola"]) * self.cfg.unidades.fator_bitola_mm
            bitola, prob_bit = self._ajustar_bitola(bitola)
            if prob_bit:
                problemas.append(prob_bit)

            # --- comprimento (pode ser faixa "880-900") --------------------
            fator_c = self.cfg.unidades.fator_comprimento_cm
            c_min = self._numero(g["comprimento"]) * fator_c
            c_max_bruto = g.get("comprimento_max")
            variavel = c_max_bruto is not None
            if variavel:
                c_max = self._numero(c_max_bruto) * fator_c
                if c_max < c_min:
                    c_min, c_max = c_max, c_min
                comprimento = (c_min + c_max) / 2.0
                # INFO e nao ALERTA: barra de comprimento variavel e uma
                # caracteristica do projeto, nao um erro de leitura. O
                # impacto medido na prancha de exemplo e de -1 a -2%.
                problemas.append(ProblemaParser(
                    TipoInconsistencia.COMPRIMENTO_VARIAVEL, Severidade.INFO,
                    f"comprimento variavel {c_min:.0f}-{c_max:.0f} cm; "
                    f"adotada a media {comprimento:.0f} cm"))
            else:
                c_max = None
                comprimento = c_min

            if not (self.cfg.parser.comprimento_min_cm <= comprimento
                    <= self.cfg.parser.comprimento_max_cm):
                problemas.append(ProblemaParser(
                    TipoInconsistencia.COMPRIMENTO_SUSPEITO, Severidade.ALERTA,
                    f"comprimento {comprimento:.0f} cm fora da faixa "
                    f"[{self.cfg.parser.comprimento_min_cm:.0f}, "
                    f"{self.cfg.parser.comprimento_max_cm:.0f}] cm"))

            # --- espacamento ----------------------------------------------
            esp_bruto = g.get("espacamento")
            espacamento = (self._numero(esp_bruto) * self.cfg.unidades.fator_espacamento_cm
                           if esp_bruto else None)

            return PosicaoBruta(
                posicao=g["posicao"].upper(),
                quantidade=quantidade,
                quantidade_explicita=quantidade_explicita,
                bitola_mm=bitola,
                comprimento_cm=comprimento,
                espacamento_cm=espacamento,
                observacao=(g.get("observacao") or "").strip(),
                comprimento_variavel=variavel,
                comprimento_min_cm=c_min if variavel else None,
                comprimento_max_cm=c_max,
                padrao=nome,
                texto_origem=trecho,
            ), problemas

        return None, problemas

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    def interpretar(self, texto_bruto: str) -> ResultadoParser:
        """Interpreta um texto do desenho.

        Trata tres situacoes de uma vez:
          1. ruido conhecido        -> ignorado=True, sem problema
          2. "A+B" em um so texto   -> duas posicoes
          3. formato desconhecido   -> problema TEXTO_NAO_INTERPRETADO
        """
        texto = self.normalizar(texto_bruto)

        if not texto or any(rx.search(texto) for rx in self._ignorar):
            return ResultadoParser([], [], ignorado=True)

        # --- caso 2: varias posicoes no mesmo texto -----------------------
        trechos = self._dividir(texto)
        posicoes: list[PosicaoBruta] = []
        problemas: list[ProblemaParser] = []
        falhou = False
        for trecho in trechos:
            pos, probs = self._interpretar_trecho(trecho)
            problemas.extend(probs)
            if pos is None:
                falhou = True
                break
            posicoes.append(pos)

        # Se a divisao por "+" nao deu certo, tenta o texto inteiro de uma vez
        # (o "+" pode ser parte de uma observacao, nao um separador).
        if falhou and len(trechos) > 1:
            posicoes, problemas = [], []
            pos, probs = self._interpretar_trecho(texto)
            problemas.extend(probs)
            if pos is not None:
                posicoes = [pos]
                falhou = False

        if falhou or not posicoes:
            return ResultadoParser([], [ProblemaParser(
                TipoInconsistencia.TEXTO_NAO_INTERPRETADO, Severidade.ERRO,
                "nenhum padrao do config.yaml casou com o texto")])

        # O texto de origem registrado e sempre o texto completo normalizado,
        # para que a conferencia no CAD seja possivel.
        for p in posicoes:
            p.texto_origem = texto
        return ResultadoParser(posicoes, problemas)

    def _dividir(self, texto: str) -> list[str]:
        """Separa "2N50-Ø10 C=300+2N51-Ø10 C=250" em dois trechos."""
        seps = self.cfg.parser.separadores_multiplas_posicoes
        if not seps:
            return [texto]
        padrao = "|".join(re.escape(s) for s in seps)
        partes = [p.strip() for p in re.split(padrao, texto) if p.strip()]
        return partes or [texto]

    # ------------------------------------------------------------------
    def e_ruido(self, texto_bruto: str) -> bool:
        """True para texto que casa com `ignorar_textos` (cota de dobra,
        titulo, escala). Usado tambem para impedir que esse tipo de texto
        acabe virando o nome de um trecho da layer AREA."""
        texto = self.normalizar(texto_bruto)
        return not texto or any(rx.search(texto) for rx in self._ignorar)

    def nao_serve_como_rotulo(self, texto_bruto: str) -> bool:
        """Texto que nunca deve nomear uma AREA: ruido ou posicao de armadura."""
        return self.e_ruido(texto_bruto) or self.parece_armadura(texto_bruto)

    def parece_armadura(self, texto_bruto: str) -> bool:
        """Heuristica usada para achar armadura em layer que nao foi lida.

        Serve de rede de seguranca contra o filtro de layers estar apertado
        demais e o programa perder posicoes em silencio.
        """
        texto = self.normalizar(texto_bruto)
        if not texto or any(rx.search(texto) for rx in self._ignorar):
            return False
        return any(rx.match(texto) for _, rx in self._padroes)


def interpretar_lote(parser: ParserArmadura, textos: Iterable[str]) -> list[ResultadoParser]:
    """Atalho para testes e uso em lote."""
    return [parser.interpretar(t) for t in textos]
