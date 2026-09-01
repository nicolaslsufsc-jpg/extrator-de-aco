"""
Carga e validacao do config.yaml (pydantic v2).

Toda regra que muda de escritorio para escritorio vive no YAML. Este modulo
so garante que o que veio de la faz sentido, e falha cedo e com mensagem
clara quando nao faz.
"""
from __future__ import annotations

import fnmatch
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Fatores para converter qualquer unidade declarada no YAML para centimetros.
FATOR_PARA_CM: dict[str, float] = {"mm": 0.1, "cm": 1.0, "m": 100.0}


def normalizar_nome(nome: str) -> str:
    """Deixa nome de layer comparavel: sem acento, sem espaco nas pontas, maiusculo.

    Necessario porque arquivos DXF gravados em cp1252 chegam com acentos
    corrompidos e porque o CAD nao diferencia maiuscula de minuscula.
    """
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().upper()


def casa_padrao(nome: str, padroes: list[str]) -> bool:
    """True se `nome` casar com algum curinga da lista (estilo AutoCAD: *, ?)."""
    alvo = normalizar_nome(nome)
    return any(fnmatch.fnmatch(alvo, normalizar_nome(p)) for p in padroes)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =============================================================================
class ConversaoCfg(_Base):
    caminho_oda: Optional[str] = None
    versao_saida: str = "ACAD2018"
    pasta_cache: Optional[str] = None
    usar_cache: bool = True
    timeout_s: int = Field(900, gt=0)


# =============================================================================
class UnidadesCfg(_Base):
    desenho: Literal["mm", "cm", "m"] = "cm"
    comprimento_texto: Literal["mm", "cm", "m"] = "cm"
    espacamento_texto: Literal["mm", "cm", "m"] = "cm"
    bitola_texto: Literal["mm", "cm"] = "mm"

    @property
    def fator_comprimento_cm(self) -> float:
        return FATOR_PARA_CM[self.comprimento_texto]

    @property
    def fator_espacamento_cm(self) -> float:
        return FATOR_PARA_CM[self.espacamento_texto]

    @property
    def fator_bitola_mm(self) -> float:
        return 1.0 if self.bitola_texto == "mm" else 10.0


# =============================================================================
class LayersCfg(_Base):
    area: list[str] = ["AREA"]
    ignorar: list[str] = []
    texto_armadura: list[str] = ["*"]
    geometria_barra: list[str] = ["*"]
    linetypes_distribuicao: list[str] = ["*DASH*", "*TRACEJ*", "*HIDDEN*"]
    # Layers dos rotulos com a EXTENSAO da distribuicao (numeros soltos ao
    # lado da barra). E deles que sai a quantidade quando o texto da
    # armadura traz espacamento mas nao traz o numero de barras.
    texto_distribuicao: list[str] = ["*IG_DIST*", "*_DIST", "*DISTRIB*"]

    def e_ignorada(self, layer: str) -> bool:
        return casa_padrao(layer, self.ignorar)

    def e_area(self, layer: str) -> bool:
        return casa_padrao(layer, self.area)

    def e_texto_armadura(self, layer: str) -> bool:
        return not self.e_ignorada(layer) and casa_padrao(layer, self.texto_armadura)

    def e_geometria_barra(self, layer: str) -> bool:
        return not self.e_ignorada(layer) and casa_padrao(layer, self.geometria_barra)


# =============================================================================
class LeituraCfg(_Base):
    ler_paperspace: bool = False
    profundidade_blocos: int = Field(3, ge=0, le=10)
    tolerancia_fechamento_rel: float = Field(
        0.02, ge=0,
        description="Fracao do perimetro: distancia maxima entre extremos "
                    "para fechar automaticamente uma polilinha aberta.",
    )
    tolerancia_simplificacao_rel: float = Field(
        0.02, ge=0,
        description="Fracao da altura mediana do texto usada para simplificar "
                    "polilinhas antes de indexar. 0 desativa.",
    )


# =============================================================================
class PadraoRegex(_Base):
    nome: str
    descricao: str = ""
    regex: str

    @field_validator("regex")
    @classmethod
    def _compila(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"regex invalida: {exc}") from exc
        return v


class ParserCfg(_Base):
    decimal_virgula: bool = True
    quantidade_padrao: int = Field(1, ge=1)
    bitolas_validas: list[float] = [5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0, 25.0, 32.0]
    tolerancia_bitola: float = Field(0.3, ge=0)
    comprimento_min_cm: float = Field(5.0, gt=0)
    comprimento_max_cm: float = Field(2000.0, gt=0)
    separadores_multiplas_posicoes: list[str] = ["+"]
    padroes: list[PadraoRegex]
    ignorar_textos: list[str] = []
    # Codigos de controle do AutoCAD trocados antes de aplicar as regex.
    substituicoes: dict[str, str] = {}

    @model_validator(mode="after")
    def _valida(self):
        if not self.padroes:
            raise ValueError("parser.padroes nao pode ser vazio")
        if self.comprimento_max_cm <= self.comprimento_min_cm:
            raise ValueError("parser.comprimento_max_cm deve ser maior que o minimo")
        for p in self.ignorar_textos:
            try:
                re.compile(p)
            except re.error as exc:
                raise ValueError(f"parser.ignorar_textos: regex invalida {p!r}: {exc}") from exc
        return self


# =============================================================================
class AgrupamentoCfg(_Base):
    # Tolerancias em MULTIPLOS DA ALTURA MEDIANA DO TEXTO. Isso deixa o
    # programa imune a escala do desenho (o mesmo config serve para uma
    # prancha em metros e outra em centimetros).
    tolerancia_alturas: float = Field(3.0, gt=0)
    tolerancia_absoluta: Optional[float] = None   # sobrescreve, em unidades
    juntar_fragmentos: bool = True
    quebrar_mtext: bool = True


# =============================================================================
class AssociacaoCfg(_Base):
    raio_busca_alturas: float = Field(12.0, gt=0)
    raio_busca_absoluto: Optional[float] = None
    max_candidatos: int = Field(12, ge=1)
    peso_distancia: float = Field(1.0, ge=0)
    peso_angulo: float = Field(0.6, ge=0)
    angulo_max_graus: float = Field(45.0, gt=0, le=90)
    comprimento_min_barra_alturas: float = Field(2.0, ge=0)
    score_suspeito: float = Field(0.65, ge=0)
    usar_ponto_texto_se_falhar: bool = True


# =============================================================================
class AreasCfg(_Base):
    criterio_divisa: Literal["maior_parte", "centroide", "proporcional",
                             "fora_do_escopo"] = "maior_parte"
    fonte_nome: list[Literal["nome_layer", "atributo_bloco", "texto_interno",
                             "sequencial"]] = [
        "nome_layer", "atributo_bloco", "texto_interno", "sequencial"
    ]
    # Trecho desenhado em layer propria (TRECHO 01, TRECHO 02...): o nome do
    # trecho e o nome da layer. Este prefixo e removido do rotulo quando
    # `limpar_prefixo_layer` estiver ligado.
    prefixo_layer_trecho: str = "TRECHO"
    limpar_prefixo_layer: bool = False
    prefixo_sequencial: str = "AREA"
    layers_nome_area: list[str] = ["*"]
    montar_de_segmentos: bool = True
    area_minima_alturas2: float = Field(
        100.0, ge=0,
        description="Area minima do poligono, em multiplos do quadrado da "
                    "altura mediana do texto.",
    )
    # Costura de extremos soltos do contorno, em fracao da altura do
    # texto. 0.01 x 0.2 = 0.002 unidades de desenho = 1 mm real na escala
    # 1:50. Nenhum contorno intencionalmente aberto erra por tao pouco.
    tolerancia_costura_alturas: float = Field(0.01, ge=0)
    tolerancia_sobreposicao: float = Field(0.001, ge=0, le=1)
    nome_sem_area: str = "SEM_AREA"
    # Categoria das barras cortadas pelo contorno da AREA (criterio
    # `fora_do_escopo`): estao parcialmente dentro e parcialmente fora.
    nome_fora_escopo: str = "FORA_DO_ESCOPO"
    # Posicao que existe no gabarito mas nao foi localizada em nenhum
    # trecho do desenho. Entra no total (o peso nao some) em aba propria.
    nome_sem_localizacao: str = "SEM_LOCALIZACAO"
    # Fracao do comprimento da barra abaixo da qual a interseccao com o
    # poligono e considerada apenas encoste, e nao corte de verdade.
    # Evita que uma barra tangente a divisa vire "fora do escopo".
    tolerancia_corte: float = Field(0.01, ge=0, le=0.5)


# =============================================================================
class CasasDecimais(_Base):
    comprimento_unitario: int = 0
    comprimento_total: int = 2
    peso: int = 2
    percentual: int = 1


class CalculoCfg(_Base):
    # DE ONDE VEM A QUANTIDADE DE BARRAS:
    #   desenho          -> a quantidade escrita no texto de cada barra.
    #   gabarito_rateado -> a quantidade EXATA da tabela mestre, distribuida
    #                       entre os trechos na proporcao das barras
    #                       desenhadas em cada um. Necessario quando uma
    #                       barra desenhada representa varias iguais e o
    #                       multiplicador nao esta legivel no desenho.
    # DE ONDE VEM A QUANTIDADE DE BARRAS:
    #   auto             -> decide sozinho (padrao), ver limiar_recorte
    #   desenho          -> a quantidade escrita no texto de cada barra
    #   gabarito_rateado -> a quantidade EXATA da tabela mestre, distribuida
    #                       entre os trechos na proporcao das barras
    #                       desenhadas em cada um
    fonte_quantidade: Literal["auto", "desenho",
                              "gabarito_rateado"] = "auto"
    # Fracao das posicoes do gabarito que precisam aparecer no desenho
    # para o modo `auto` confiar no rateio.
    #
    # Numa prancha inteira o desenho cobre quase todas as posicoes da
    # tabela, e o rateio e o que corrige a subcontagem das barras iguais.
    # Num RECORTE do desenho a tabela continua descrevendo o pavimento
    # inteiro: rateá-la sobre as poucas barras desenhadas jogaria o
    # pavimento todo em cima delas (uma barra desenhada virando 609).
    # Abaixo deste limiar o programa reporta o que esta desenhado.
    limiar_recorte: float = Field(0.5, gt=0, le=1)
    peso_linear: dict[float, float]
    categoria_por_bitola: dict[float, str] = {}
    categoria_por_posicao: dict[str, str] = {}
    perda_percentual: float = Field(0.10, ge=0, le=1)
    recalcular_quantidade: bool = False
    tolerancia_divergencia_qtd: float = Field(0.15, ge=0)
    # Barra escrita com espacamento mas SEM quantidade ("N3-Ø8c/10 C=300")
    # tem a quantidade recuperada por ceil(extensao / espacamento), com a
    # extensao lida do rotulo de distribuicao ao lado da barra.
    # Desligado, cada uma dessas conta como 1 barra - subcontagem de 10 a
    # 25 vezes numa laje.
    recuperar_quantidade_distribuicao: bool = True
    # Raio de busca do rotulo de extensao, em multiplos do raio de
    # associacao texto-barra.
    raio_extensao_fator: float = Field(2.0, gt=0)
    # Dois rotulos a menos desta diferenca relativa de distancia deixam a
    # escolha ambigua, e a posicao e reportada para conferencia.
    margem_ambiguidade: float = Field(0.2, ge=0)
    casas_decimais: CasasDecimais = CasasDecimais()

    @field_validator("peso_linear", "categoria_por_bitola", mode="before")
    @classmethod
    def _chaves_float(cls, v: Any) -> Any:
        """YAML pode entregar as bitolas como string ("12.5"); normaliza."""
        if isinstance(v, dict):
            return {float(k): val for k, val in v.items()}
        return v

    def peso_linear_de(self, bitola_mm: float) -> Optional[float]:
        return self.peso_linear.get(round(bitola_mm, 3))

    def categoria_de(self, bitola_mm: float, posicao: str) -> str:
        if posicao in self.categoria_por_posicao:
            return self.categoria_por_posicao[posicao]
        return self.categoria_por_bitola.get(round(bitola_mm, 3), "CA-50")


# =============================================================================
class LimiteArea(_Base):
    total: Optional[float] = None
    por_bitola: dict[float, float] = {}

    @field_validator("por_bitola", mode="before")
    @classmethod
    def _chaves_float(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {float(k): val for k, val in v.items()}
        return v


class LimitesCfg(_Base):
    base_comparacao: Literal["peso_com_perda", "peso_liquido"] = "peso_com_perda"
    percentual_alerta: float = Field(0.90, gt=0, le=1)
    # Eficacia = peso atribuido a trechos nomeados / peso total extraido.
    # Abaixo do minimo a aba COMPARACAO reprova; a meta e 100%.
    eficacia_minima: float = Field(0.96, gt=0, le=1)
    eficacia_meta: float = Field(0.999, gt=0, le=1)
    por_area: dict[str, LimiteArea] = {}
    arquivo_limites: Optional[str] = None


# =============================================================================
class SentidoCfg(_Base):
    """Classificacao da armadura pela direcao da barra no desenho.

    Serve para separar, dentro da aba de cada trecho, a armadura de cada
    sentido (as duas direcoes de uma laje armada em cruz).
    """
    # Meia-abertura, em graus, das faixas horizontal e vertical.
    tolerancia_graus: float = Field(15.0, gt=0, le=45)
    nome_horizontal: str = "SENTIDO X (horizontal)"
    nome_vertical: str = "SENTIDO Y (vertical)"
    nome_inclinada: str = "SENTIDO INCLINADO"
    nome_indefinido: str = "SEM GEOMETRIA"

    def classificar(self, angulo: Optional[float]) -> str:
        """Angulo 0-180 -> nome do sentido."""
        if angulo is None:
            return self.nome_indefinido
        a = float(angulo) % 180.0
        t = self.tolerancia_graus
        if a <= t or a >= 180.0 - t:
            return self.nome_horizontal
        if abs(a - 90.0) <= t:
            return self.nome_vertical
        return self.nome_inclinada

    @property
    def ordem(self) -> list[str]:
        """Ordem fixa das secoes dentro da aba do trecho."""
        return [self.nome_horizontal, self.nome_vertical,
                self.nome_inclinada, self.nome_indefinido]


class TabelaMestreCfg(_Base):
    """Tabela de aco desenhada na propria prancha - o gabarito.

    Serve para medir o % de acerto da extracao: o que foi lido das barras
    contra o que o projeto declara. Estas layers continuam FORA do
    quantitativo (senao o aco seria contado duas vezes); sao lidas apenas
    para a comparacao.
    """
    ativar: bool = True
    layers: list[str] = ["TABFER*", "TEXTO_TABELAS", "TABELAS", "*RESUMO*"]
    # Diferenca relativa aceita entre o peso declarado na tabela e o peso
    # recalculado por (comprimento x peso linear).
    # O papel desta validacao e rejeitar leitura ESTRUTURALMENTE errada -
    # celula intrusa faz o peso sair centenas de vezes maior, nao 6%.
    # Apertar demais derruba linha boa: na prancha de exemplo a posicao 4
    # declara 5,7 kg onde a conta da 5,37 (arredondamento do Eberick).
    tolerancia_validacao: float = Field(0.15, gt=0, le=0.5)
    # Faixas do % de acerto na aba COMPARACAO FINAL.
    acerto_minimo: float = Field(0.96, gt=0, le=1)
    acerto_meta: float = Field(0.99, gt=0, le=1)


class CoresCfg(_Base):
    ok: str = "#C6EFCE"
    alerta: str = "#FFEB9C"
    excedido: str = "#FFC7CE"
    cabecalho: str = "#1F4E78"
    subtotal: str = "#DDEBF7"


class SaidaCfg(_Base):
    # MODO LIMPO: a planilha fica so com as abas de trecho, o RESUMO
    # GERAL e a COMPARACAO FINAL.
    # A tabela CONTINUA com uma linha por posicao, com comprimento
    # unitario - e uma lista de corte e dobra, essa informacao nao pode
    # sumir. O que sai e o bloco DETALHAMENTO (uma linha por texto lido
    # no desenho) e as abas VERIFICACAO e INCONSISTENCIAS.
    modo_limpo: bool = False
    abas_por_area: bool = True
    # Dentro da aba de cada trecho, separar a armadura por sentido.
    agrupar_por_sentido: bool = True
    max_abas_area: int = Field(60, ge=0)
    incluir_prancha: bool = True
    incluir_diagnostico: bool = True
    cores: CoresCfg = CoresCfg()


# =============================================================================
class LogCfg(_Base):
    nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    arquivo: str = "extrator_aco.log"
    sobrescrever: bool = True


# =============================================================================
class Config(_Base):
    conversao: ConversaoCfg = ConversaoCfg()
    unidades: UnidadesCfg = UnidadesCfg()
    layers: LayersCfg = LayersCfg()
    leitura: LeituraCfg = LeituraCfg()
    parser: ParserCfg
    agrupamento: AgrupamentoCfg = AgrupamentoCfg()
    associacao: AssociacaoCfg = AssociacaoCfg()
    areas: AreasCfg = AreasCfg()
    sentido: SentidoCfg = SentidoCfg()
    tabela_mestre: TabelaMestreCfg = TabelaMestreCfg()
    calculo: CalculoCfg
    limites: LimitesCfg = LimitesCfg()
    saida: SaidaCfg = SaidaCfg()
    log: LogCfg = LogCfg()

    # ---------------------------------------------------------------------
    # Tolerancias efetivas: dependem da altura mediana do texto da prancha,
    # medida na leitura. Enquanto nao houver medicao, cai no valor de 1.0.
    # ---------------------------------------------------------------------
    altura_referencia: float = 1.0

    # Nome do projeto, usado como prefixo das abas do Excel. Preenchido em
    # tempo de execucao a partir do nome do arquivo/pasta de entrada
    # (ou de --projeto), nao do YAML.
    projeto: str = ""

    def calibrar(self, altura_mediana: float) -> None:
        """Fixa a altura de texto que serve de referencia para as tolerancias."""
        if altura_mediana and altura_mediana > 0:
            self.altura_referencia = float(altura_mediana)

    @property
    def tol_agrupamento(self) -> float:
        if self.agrupamento.tolerancia_absoluta is not None:
            return self.agrupamento.tolerancia_absoluta
        return self.agrupamento.tolerancia_alturas * self.altura_referencia

    @property
    def raio_associacao(self) -> float:
        if self.associacao.raio_busca_absoluto is not None:
            return self.associacao.raio_busca_absoluto
        return self.associacao.raio_busca_alturas * self.altura_referencia

    @property
    def comprimento_min_barra(self) -> float:
        return self.associacao.comprimento_min_barra_alturas * self.altura_referencia

    @property
    def area_minima(self) -> float:
        return self.areas.area_minima_alturas2 * self.altura_referencia ** 2

    @property
    def tol_costura_area(self) -> float:
        """Tolerancia para costurar extremos soltos do contorno de trecho.

        Fracao minuscula da altura do texto: costura ruido numerico de
        coordenada (ordem de 1e-13) sem fechar contorno de verdade aberto,
        que erra por centimetros, nao por bilionesimos.
        """
        return self.areas.tolerancia_costura_alturas * self.altura_referencia

    @property
    def tol_simplificacao(self) -> float:
        return self.leitura.tolerancia_simplificacao_rel * self.altura_referencia


# =============================================================================
def carregar_config(caminho: str | Path) -> Config:
    """Le e valida o config.yaml. Erros de configuracao param o programa aqui."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(
            f"config.yaml nao encontrado em {caminho}.\n"
            "Copie o config.yaml de exemplo que acompanha o programa."
        )
    with caminho.open("r", encoding="utf-8") as fh:
        dados = yaml.safe_load(fh) or {}
    try:
        return Config.model_validate(dados)
    except Exception as exc:
        raise ValueError(
            f"config.yaml invalido ({caminho}):\n{exc}"
        ) from exc
