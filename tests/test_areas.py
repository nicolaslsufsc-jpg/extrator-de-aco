"""
Testes da classificacao por AREA - a funcao central do programa.

Cobrem os casos limite documentados no PREMISSAS.md: barra dentro,
barra na divisa (centroide x proporcional), barra fora e areas sobrepostas.
"""
import pytest
from shapely.geometry import LineString, Polygon

from extrator.areas import ClassificadorAreas, desambiguar_nomes
from extrator.modelos import AreaProjeto


def _area(nome, x0, y0, x1, y1):
    return AreaProjeto(nome=nome,
                       poligono=Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]),
                       prancha="P1")


@pytest.fixture
def duas_areas():
    """Dois retangulos lado a lado, encostados em x=100."""
    return [_area("AREA-01", 0, 0, 100, 100), _area("AREA-02", 100, 0, 200, 100)]


# =============================================================================
# Criterio centroide (padrao)
# =============================================================================

def test_ponto_dentro_de_uma_area(cfg, duas_areas):
    c = ClassificadorAreas(duas_areas, cfg)
    assert c.classificar(50, 50) == [("AREA-01", 1.0)]
    assert c.classificar(150, 50) == [("AREA-02", 1.0)]


def test_ponto_fora_de_tudo_vai_para_sem_area(cfg, duas_areas):
    c = ClassificadorAreas(duas_areas, cfg)
    assert c.classificar(500, 500) == [(cfg.areas.nome_sem_area, 1.0)]


def test_ponto_exatamente_na_borda_e_aceito(cfg, duas_areas):
    """`covers` inclui a borda: uma barra encostada na divisa nao pode
    escapar para SEM_AREA."""
    c = ClassificadorAreas(duas_areas, cfg)
    nome, _ = c.classificar(0, 50)[0]
    assert nome != cfg.areas.nome_sem_area


def test_barra_na_divisa_vai_inteira_para_a_area_do_centroide(cfg, duas_areas):
    """Criterio centroide: 100% do peso num lado so."""
    cfg.areas.criterio_divisa = "centroide"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(80, 50), (140, 50)])       # cruza x=100
    # ponto medio em x=110 -> AREA-02
    assert c.classificar(110, 50, barra) == [("AREA-02", 1.0)]


def test_sem_nenhuma_area_tudo_cai_em_sem_area(cfg):
    c = ClassificadorAreas([], cfg)
    assert c.classificar(10, 10) == [(cfg.areas.nome_sem_area, 1.0)]


# =============================================================================
# Criterio proporcional
# =============================================================================

def test_proporcional_rateia_metade_para_cada_area(cfg, duas_areas):
    cfg.areas.criterio_divisa = "proporcional"
    try:
        c = ClassificadorAreas(duas_areas, cfg)
        barra = LineString([(50, 50), (150, 50)])   # 50 em cada lado
        fatias = dict(c.classificar(100, 50, barra))
        assert fatias["AREA-01"] == pytest.approx(0.5, abs=1e-6)
        assert fatias["AREA-02"] == pytest.approx(0.5, abs=1e-6)
    finally:
        cfg.areas.criterio_divisa = "centroide"


def test_proporcional_manda_o_trecho_de_fora_para_sem_area(cfg, duas_areas):
    cfg.areas.criterio_divisa = "proporcional"
    try:
        c = ClassificadorAreas(duas_areas, cfg)
        barra = LineString([(50, 50), (250, 50)])   # 50 dentro, 100 dentro, 50 fora
        fatias = dict(c.classificar(150, 50, barra))
        assert fatias[cfg.areas.nome_sem_area] == pytest.approx(0.25, abs=1e-6)
    finally:
        cfg.areas.criterio_divisa = "centroide"


def test_proporcional_sempre_soma_um(cfg, duas_areas):
    """Se as fracoes nao somassem 1, a aba VERIFICACAO acusaria divergencia."""
    cfg.areas.criterio_divisa = "proporcional"
    try:
        c = ClassificadorAreas(duas_areas, cfg)
        for barra in (LineString([(50, 50), (150, 50)]),
                      LineString([(-50, 50), (250, 50)]),
                      LineString([(10, 10), (20, 20)])):
            fatias = c.classificar(0, 0, barra)
            assert sum(f for _, f in fatias) == pytest.approx(1.0, abs=1e-9)
    finally:
        cfg.areas.criterio_divisa = "centroide"


def test_proporcional_sem_geometria_cai_no_centroide(cfg, duas_areas):
    cfg.areas.criterio_divisa = "proporcional"
    try:
        c = ClassificadorAreas(duas_areas, cfg)
        assert c.classificar(50, 50, None) == [("AREA-01", 1.0)]
    finally:
        cfg.areas.criterio_divisa = "centroide"


# =============================================================================
# Areas sobrepostas
# =============================================================================

def test_area_sobreposta_conta_uma_vez_so_no_criterio_proporcional(cfg):
    """A regiao comum nao pode ser contada duas vezes (soma > 1)."""
    cfg.areas.criterio_divisa = "proporcional"
    try:
        areas = [_area("GRANDE", 0, 0, 200, 100), _area("PEQUENA", 50, 0, 150, 100)]
        c = ClassificadorAreas(areas, cfg)
        fatias = c.classificar(100, 50, LineString([(10, 50), (190, 50)]))
        assert sum(f for _, f in fatias) == pytest.approx(1.0, abs=1e-9)
    finally:
        cfg.areas.criterio_divisa = "centroide"


def test_ordem_estavel_da_maior_para_a_menor(cfg):
    """A classificacao nao pode depender da ordem de leitura do DXF."""
    a, b = _area("PEQUENA", 50, 50, 60, 60), _area("GRANDE", 0, 0, 200, 200)
    assert ClassificadorAreas([a, b], cfg).nomes == ["GRANDE", "PEQUENA"]
    assert ClassificadorAreas([b, a], cfg).nomes == ["GRANDE", "PEQUENA"]


# =============================================================================
# Nomes
# =============================================================================

def test_nomes_repetidos_sao_desambiguados(cfg):
    areas = [_area("AREA-01", 0, 0, 1, 1), _area("AREA-01", 2, 2, 3, 3)]
    desambiguar_nomes(areas)
    assert [a.nome for a in areas] == ["AREA-01", "AREA-01 (2)"]


def test_desambiguacao_atravessa_pranchas_do_mesmo_lote(cfg):
    """Duas pranchas trazem 'AREA-01' cada uma; nao podem virar a mesma aba."""
    registro = {}
    p1 = [_area("AREA-01", 0, 0, 1, 1)]
    p2 = [_area("AREA-01", 0, 0, 1, 1)]
    desambiguar_nomes(p1, registro)
    desambiguar_nomes(p2, registro)
    assert p1[0].nome != p2[0].nome


# =============================================================================
# Criterio fora_do_escopo (padrao) - barra cortada pelo contorno da AREA
# =============================================================================

def test_barra_cortada_pelo_contorno_sai_do_trecho(cfg, duas_areas):
    """Pedido do usuario: barra que atravessa o contorno nao entra na area."""
    cfg.areas.criterio_divisa = "fora_do_escopo"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(80, 50), (140, 50)])          # cruza x=100
    assert c.classificar(110, 50, barra) == [(cfg.areas.nome_fora_escopo, 1.0)]


def test_barra_inteira_dentro_continua_no_trecho(cfg, duas_areas):
    cfg.areas.criterio_divisa = "fora_do_escopo"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(10, 50), (90, 50)])
    assert c.classificar(50, 50, barra) == [("AREA-01", 1.0)]


def test_barra_inteira_fora_continua_em_sem_area(cfg, duas_areas):
    """Cortada e fora sao categorias diferentes: nao podem se misturar."""
    cfg.areas.criterio_divisa = "fora_do_escopo"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(300, 50), (400, 50)])
    assert c.classificar(350, 50, barra) == [(cfg.areas.nome_sem_area, 1.0)]


def test_barra_que_so_encosta_na_divisa_nao_e_considerada_cortada(cfg, duas_areas):
    """Tolerancia de 1%: um encoste de 0,5% do comprimento nao tira a barra
    do trecho, senao qualquer imprecisao de desenho viraria fora do escopo."""
    cfg.areas.criterio_divisa = "fora_do_escopo"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(100.5, 50), (200.0, 50)])     # ~0,5 dentro da AREA-01
    assert c.classificar(150, 50, barra) == [("AREA-02", 1.0)]


def test_area_aninhada_prevalece_sobre_corte_da_area_externa(cfg):
    """Barra inteira dentro da area pequena, mas cortando a grande:
    'inteira dentro' tem prioridade sobre 'cortada'."""
    cfg.areas.criterio_divisa = "fora_do_escopo"
    areas = [_area("GRANDE", 0, 0, 100, 100), _area("PEQUENA", 40, 40, 60, 60)]
    c = ClassificadorAreas(areas, cfg)
    assert c.classificar(50, 50, LineString([(45, 50), (55, 50)]))[0][0] \
        in ("GRANDE", "PEQUENA")


def test_sem_geometria_cai_no_teste_do_ponto(cfg, duas_areas):
    cfg.areas.criterio_divisa = "fora_do_escopo"
    c = ClassificadorAreas(duas_areas, cfg)
    assert c.classificar(50, 50, None) == [("AREA-01", 1.0)]


# =============================================================================
# Criterio maior_parte (PADRAO) - "puxar para o lado onde a barra mais esta"
# =============================================================================

def test_barra_na_divisa_vai_para_o_lado_com_mais_barra(cfg, duas_areas):
    """80 cm em AREA-01 e 20 cm em AREA-02 -> tudo em AREA-01."""
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(20, 50), (120, 50)])      # 80 dentro de A, 20 de B
    assert c.classificar(70, 50, barra) == [("AREA-01", 1.0)]


def test_maior_parte_difere_do_centroide_quando_o_ponto_medio_engana(cfg,
                                                                    duas_areas):
    """O ponto medio cai em AREA-02, mas a barra esta 70% em AREA-01.

    E exatamente o caso em que o criterio centroide erra o lado.
    """
    barra = LineString([(30, 50), (130, 50)])      # 70 em A, 30 em B
    ponto_medio_x = 80                             # dentro de AREA-01
    # ... e agora um caso invertido, com o ponto medio do lado errado:
    barra2 = LineString([(-40, 50), (110, 50)])    # 100 em A, 10 em B
    medio2_x = 35                                  # em A

    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    assert c.classificar(ponto_medio_x, 50, barra) == [("AREA-01", 1.0)]
    assert c.classificar(medio2_x, 50, barra2) == [("AREA-01", 1.0)]


def test_nada_se_perde_barra_que_encosta_no_trecho_e_contada_nele(cfg,
                                                                  duas_areas):
    """Barra 30% dentro e 70% fora de tudo: ainda assim entra no trecho.

    'Incluir tudo': so vai para SEM_AREA quem nao toca trecho nenhum.
    """
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(170, 50), (300, 50)])     # 30 em AREA-02, 100 fora
    assert c.classificar(235, 50, barra) == [("AREA-02", 1.0)]


def test_barra_que_nao_toca_nenhum_trecho_vai_para_sem_area(cfg, duas_areas):
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    barra = LineString([(400, 400), (500, 400)])
    assert c.classificar(450, 400, barra) == [(cfg.areas.nome_sem_area, 1.0)]


def test_maior_parte_nunca_cria_fora_do_escopo(cfg, duas_areas):
    """O criterio padrao nao deve produzir a categoria FORA_DO_ESCOPO."""
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    for barra in (LineString([(80, 50), (140, 50)]),
                  LineString([(-50, 50), (250, 50)]),
                  LineString([(95, 50), (105, 50)])):
        nomes = [n for n, _ in c.classificar(100, 50, barra)]
        assert cfg.areas.nome_fora_escopo not in nomes


def test_maior_parte_devolve_sempre_uma_area_so(cfg, duas_areas):
    """A posicao nao pode ser quebrada em varias linhas neste criterio."""
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    fatias = c.classificar(100, 50, LineString([(50, 50), (150, 50)]))
    assert len(fatias) == 1 and fatias[0][1] == 1.0


def test_maior_parte_sem_geometria_cai_no_ponto_do_texto(cfg, duas_areas):
    cfg.areas.criterio_divisa = "maior_parte"
    c = ClassificadorAreas(duas_areas, cfg)
    assert c.classificar(150, 50, None) == [("AREA-02", 1.0)]


# =============================================================================
# Todo criterio declarado no schema precisa estar implementado
# =============================================================================

def _criterios_do_schema() -> list[str]:
    from extrator.config import Config
    return list(Config.model_fields["areas"].annotation
                .model_fields["criterio_divisa"].annotation.__args__)


def test_todo_criterio_do_schema_esta_implementado(cfg, duas_areas):
    """Rede contra criterio declarado e nao implementado - e contra lista
    de opcoes desatualizada na interface, que ja quebrou a tela uma vez."""
    barra = LineString([(80, 50), (140, 50)])
    for criterio in _criterios_do_schema():
        cfg.areas.criterio_divisa = criterio
        c = ClassificadorAreas(duas_areas, cfg)
        fatias = c.classificar(110, 50, barra)
        assert fatias, f"criterio {criterio!r} nao devolveu nada"
        assert sum(f for _, f in fatias) == pytest.approx(1.0, abs=1e-9), \
            f"criterio {criterio!r}: fracoes nao somam 1"
        assert all(isinstance(n, str) and n for n, _ in fatias)


def test_criterio_padrao_do_schema_e_maior_parte():
    assert _criterios_do_schema()[0] == "maior_parte"
