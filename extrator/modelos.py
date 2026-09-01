"""
Modelos de dominio do extrator de aco.

Este modulo so define estruturas de dados: nao le arquivo, nao calcula nada.
Todas as etapas do pipeline trocam informacao atraves destas classes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# `Any` e usado nas anotacoes de geometria para nao obrigar o import do
# shapely em quem so precisa das estruturas (testes do parser, por exemplo).


# =============================================================================
# ENTIDADES BRUTAS LIDAS DO DXF
# =============================================================================

@dataclass(slots=True)
class TextoDXF:
    """Um TEXT ou MTEXT lido do desenho, ja normalizado.

    O texto guardado em `conteudo` ja passou pela troca dos codigos de
    controle do AutoCAD (%%c -> Ø) feita na leitura.
    """
    handle: str            # identificador unico da entidade no DXF
    conteudo: str          # texto normalizado, uma linha
    conteudo_bruto: str    # texto exatamente como estava no arquivo
    x: float
    y: float
    altura: float          # altura do caractere (usada para calibrar tolerancias)
    rotacao: float         # graus, 0-360
    layer: str
    prancha: str           # nome do arquivo de origem
    # Quando um MTEXT de varias linhas e quebrado, todas as linhas geradas
    # compartilham o handle do MTEXT original e recebem um indice.
    indice_linha: int = 0


@dataclass(slots=True)
class GeometriaDXF:
    """Uma linha/polilinha/arco que pode ser o desenho de uma barra."""
    handle: str
    geometria: Any            # shapely LineString
    comprimento_desenho: float
    angulo: float             # graus, 0-180 (direcao principal)
    layer: str
    linetype: str
    prancha: str
    # True quando o linetype/layer indica linha tracejada de distribuicao.
    e_distribuicao: bool = False


@dataclass(slots=True)
class AreaProjeto:
    """Um poligono da layer AREA, ja fechado e nomeado."""
    nome: str
    poligono: Any             # shapely Polygon
    prancha: str
    # Layer de origem: e ela que da nome ao trecho quando as regioes sao
    # desenhadas em layers separadas (TRECHO 01, TRECHO 02...).
    layer: str = ""
    # Como o nome foi obtido:
    # nome_layer | atributo_bloco | texto_interno | sequencial
    origem_nome: str = "sequencial"
    # Handles das entidades que formaram o poligono (rastreabilidade).
    handles: tuple[str, ...] = ()
    # True quando o poligono foi montado a partir de linhas soltas em vez
    # de uma polilinha ja fechada. Vale conferir no desenho.
    montado_de_segmentos: bool = False


# =============================================================================
# RESULTADO DO PARSER
# =============================================================================

@dataclass(slots=True)
class PosicaoBruta:
    """Resultado da interpretacao de UM texto de armadura.

    Ainda sem geometria e sem area: e so o conteudo do texto traduzido
    para numeros. Unidades ja convertidas para cm (comprimento/espacamento)
    e mm (bitola).
    """
    posicao: str                       # "1", "215B"
    quantidade: int
    bitola_mm: float
    comprimento_cm: float              # se variavel, e a media de min/max
    espacamento_cm: Optional[float] = None
    observacao: str = ""
    # Comprimento variavel: "C=880-900" no desenho.
    comprimento_variavel: bool = False
    comprimento_min_cm: Optional[float] = None
    comprimento_max_cm: Optional[float] = None
    # False quando o texto nao trazia o numero de barras e o parser
    # assumiu `quantidade_padrao`. E o sinal de que a quantidade precisa
    # ser recuperada pela extensao da distribuicao.
    quantidade_explicita: bool = True
    # Nome do padrao regex que casou (diagnostico).
    padrao: str = ""
    texto_origem: str = ""


# =============================================================================
# POSICAO CONSOLIDADA (texto + barra + area + peso)
# =============================================================================

@dataclass(slots=True)
class PosicaoArmadura:
    """Uma posicao de armadura completa, pronta para o relatorio."""
    # --- identificacao ---
    id: str
    prancha: str
    posicao: str
    # --- dados do texto ---
    # `quantidade` e a que vale no quantitativo. Quando a fonte e o
    # gabarito, ela vem rateada da tabela mestre; `quantidade_desenho`
    # guarda o que estava escrito na prancha, para a coluna de conferencia.
    quantidade: float
    bitola_mm: float
    comprimento_unit_cm: float
    espacamento_cm: Optional[float]
    texto_origem: str
    observacao: str = ""
    comprimento_variavel: bool = False
    # --- geometria / associacao ---
    x_texto: float = 0.0
    y_texto: float = 0.0
    handle_texto: str = ""
    layer_texto: str = ""
    handle_barra: Optional[str] = None
    geometria_barra: Any = None        # shapely LineString ou None
    x_repr: float = 0.0                # ponto usado no teste ponto-em-poligono
    y_repr: float = 0.0
    score_associacao: Optional[float] = None
    associacao_duvidosa: bool = False
    # --- classificacao por area ---
    area: str = ""
    fracao_area: float = 1.0           # 1.0 no criterio centroide
    # --- sentido da armadura (direcao da barra no desenho) ---
    angulo_barra: Optional[float] = None   # graus 0-180
    sentido: str = ""                      # X (horizontal) | Y (vertical) | ...
    # --- calculo ---
    categoria: str = "CA-50"
    peso_linear_kg_m: float = 0.0
    comprimento_total_m: float = 0.0
    peso_liquido_kg: float = 0.0
    peso_com_perda_kg: float = 0.0
    # --- formato da barra (corte e dobra), vindo da tabela do projeto ---
    # Pernas na ordem da tabela; a decomposicao em Dobra|Reta|Dobra e
    # feita na exportacao. Vazio quando o formato nao foi identificado.
    pernas_cm: tuple = ()
    dobra1_cm: Optional[float] = None
    reta_cm: Optional[float] = None
    dobra2_cm: Optional[float] = None
    # --- procedencia da quantidade ---
    quantidade_explicita: bool = True
    extensao_distribuicao_cm: Optional[float] = None
    quantidade_desenho: float = 0.0
    origem_quantidade: str = "desenho"   # desenho | gabarito


# =============================================================================
# INCONSISTENCIAS
# =============================================================================

class TipoInconsistencia(str, Enum):
    """Catalogo fechado dos problemas que o programa sabe reportar."""
    TEXTO_NAO_INTERPRETADO = "Texto nao interpretado pelo parser"
    TEXTO_SEM_GEOMETRIA = "Texto sem geometria de barra correspondente"
    BARRA_SEM_AREA = "Armadura fora de qualquer AREA"
    ASSOCIACAO_DUVIDOSA = "Associacao texto-barra duvidosa"
    AREA_SOBREPOSTA = "Poligonos de AREA sobrepostos"
    AREA_NAO_FECHADA = "Polilinha da layer AREA nao fechada"
    AREA_COSTURADA = "Contorno de trecho fechado automaticamente"
    AREA_DEGENERADA = "Poligono de AREA menor que a area minima"
    BITOLA_INVALIDA = "Bitola fora da tabela NBR 7480"
    COMPRIMENTO_SUSPEITO = "Comprimento fora da faixa aceitavel"
    COMPRIMENTO_VARIAVEL = "Comprimento variavel (C=a-b) - estimado pela media"
    DIVERGENCIA_QUANTIDADE = "Quantidade do texto diverge da linha de distribuicao"
    TEXTO_EM_LAYER_NAO_LIDA = "Texto com formato de armadura em layer nao lida"
    SEM_PESO_LINEAR = "Bitola sem peso linear cadastrado"
    TABELA_MESTRE = "Leitura da tabela mestre do desenho"
    POSICAO_SEM_LOCALIZACAO = "Posicao do gabarito nao localizada no desenho"
    POSICAO_FORA_DO_GABARITO = "Posicao no desenho que nao consta no gabarito"
    COMPRIMENTO_DIVERGE_DO_GABARITO = (
        "Comprimento do desenho diferente do da tabela do projeto")
    DISTRIBUICAO_SEM_EXTENSAO = (
        "Barra distribuida sem rotulo de extensao - quantidade subcontada")
    DISTRIBUICAO_AMBIGUA = (
        "Dois rotulos de extensao equidistantes - quantidade a conferir")
    CONVERSAO_FALHOU = "Falha na conversao DWG para DXF"
    RECORTE_DETECTADO = "Desenho e um recorte - tabela do projeto nao usada"
    RESUMO = "Resumo informativo"


class Severidade(str, Enum):
    ERRO = "ERRO"          # o quantitativo esta errado ou incompleto
    ALERTA = "ALERTA"      # pode estar errado, exige conferencia
    INFO = "INFO"          # informativo


@dataclass(slots=True)
class Inconsistencia:
    """Um problema encontrado, com contexto suficiente para achar no CAD."""
    tipo: TipoInconsistencia
    severidade: Severidade
    descricao: str
    prancha: str = ""
    layer: str = ""
    handle: str = ""
    texto: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    # Quantas ocorrencias identicas foram agrupadas nesta linha.
    ocorrencias: int = 1


# =============================================================================
# ESTATISTICAS E RESULTADO FINAL
# =============================================================================

@dataclass
class Estatisticas:
    """Contadores do processamento, escritos no log e no Excel."""
    arquivos_lidos: int = 0
    arquivos_convertidos: int = 0
    entidades_totais: int = 0
    textos_lidos: int = 0
    textos_ignorados_ruido: int = 0       # casaram com parser.ignorar_textos
    textos_em_layers_ignoradas: int = 0   # layer fora do escopo (tabela, cota)
    textos_interpretados: int = 0
    textos_nao_interpretados: int = 0
    posicoes_geradas: int = 0
    geometrias_lidas: int = 0
    geometrias_barra: int = 0
    associacoes_ok: int = 0
    associacoes_duvidosas: int = 0
    associacoes_falharam: int = 0
    areas_encontradas: int = 0
    posicoes_sem_area: int = 0
    posicoes_fora_escopo: int = 0   # cortadas pelo contorno da AREA
    posicoes_sem_localizacao: int = 0
    posicoes_fora_do_gabarito: int = 0
    escala_estimada: Optional[float] = None   # cm reais por unidade de desenho
    linhas_tabela_mestre: int = 0
    peso_tabela_mestre_kg: float = 0.0
    altura_texto_mediana: Optional[float] = None
    tempo_s: float = 0.0
    # Contagem de posicoes por layer de origem (diagnostico de filtro).
    posicoes_por_layer: dict[str, int] = field(default_factory=dict)


@dataclass
class ResultadoProcessamento:
    """Tudo que o pipeline produz. A exportacao consome apenas isto."""
    posicoes: list[PosicaoArmadura] = field(default_factory=list)
    # Linhas da tabela de aco desenhada na prancha - o gabarito contra o
    # qual o extraido e conferido. Vazia quando a leitura esta desligada
    # ou o desenho nao tem tabela.
    tabela_mestre: list = field(default_factory=list)
    areas: list[AreaProjeto] = field(default_factory=list)
    inconsistencias: list[Inconsistencia] = field(default_factory=list)
    estatisticas: Estatisticas = field(default_factory=Estatisticas)
    pranchas: list[str] = field(default_factory=list)

    def adicionar(self, inc: Inconsistencia) -> None:
        self.inconsistencias.append(inc)
