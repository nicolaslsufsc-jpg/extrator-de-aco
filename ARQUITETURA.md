# ARQUITETURA — Extrator de Aço

## Pipeline (uma direção, cada etapa testável isoladamente)

```
 pasta/*.dwg
     │
     ▼
┌──────────────────┐  conversor.py      DWG → DXF via ODA File Converter
│ 1. CONVERSÃO     │  ─ localiza o executável, converte a pasta de uma vez,
└────────┬─────────┘    cacheia por data; DXF de entrada passa direto
         ▼
┌──────────────────┐  leitura.py        ezdxf → entidades em WCS
│ 2. LEITURA       │  ─ explode blocos, filtra layers, separa em
│                  │    Textos | Barras | Linhas de distribuição | AREA
│                  │  ─ mede a ALTURA MEDIANA DO TEXTO → calibra tudo
└────────┬─────────┘  ─ monta polígonos de AREA, inclusive de LINEs soltas
         ▼
┌──────────────────┐  parser_texto.py   regex de config.yaml → PosicaoBruta
│ 3. PARSER        │  ─ troca %%c → Ø, separa "A+B", trata C=880-900
└────────┬─────────┘  ─ falha vira inconsistência, nunca descarte silencioso
         ▼
┌──────────────────┐  agrupamento.py    grid hashing + union-find
│ 4. AGRUPAMENTO   │  ─ textos empilhados viram um grupo (posições distintas)
└────────┬─────────┘  ─ remonta fragmentos que o CAD quebrou em dois
         ▼
┌──────────────────┐  associacao.py     STRtree (O(log n) por consulta)
│ 5. ASSOCIAÇÃO    │  ─ score = distância + desalinhamento angular
└────────┬─────────┘  ─ atribuição exclusiva (gulosa) dentro do grupo
         ▼
┌──────────────────┐  areas.py          STRtree + ponto-em-polígono
│ 6. CLASSIFICAÇÃO │  ─ critério centroide OU rateio proporcional
└────────┬─────────┘  ─ detecta sobreposição e polilinha aberta
         ▼
┌──────────────────┐  calculo.py        NBR 7480 → comprimento, peso, perda
│ 7. CÁLCULO       │  ─ categoria CA-50/CA-60, agregações em pandas
└────────┬─────────┘  ─ confere quantidade × linha de distribuição
         ▼
┌──────────────────┐  exportacao.py     xlsxwriter
│ 8. EXPORTAÇÃO    │  ─ RESUMO GERAL | uma aba por AREA | VERIFICAÇÃO
└──────────────────┘    | INCONSISTÊNCIAS
```

`pipeline.py` orquestra e devolve um `ResultadoProcessamento`.
`app.py` (CLI) e `streamlit_app.py` (UI) são cascas em volta dele.

Cada prancha é processada **inteira** antes da próxima, e classificada
**apenas contra as suas próprias áreas** — assim duas pranchas desenhadas
nas mesmas coordenadas não misturam trechos. Os nomes de área são
desambiguados por um registro global ao longo do lote.

## Módulos

| Arquivo | Responsabilidade | Não faz |
|---|---|---|
| `extrator/config.py` | carrega e valida `config.yaml` (pydantic), resolve tolerâncias calibradas | I/O de desenho |
| `extrator/modelos.py` | dataclasses do domínio e catálogo de inconsistências | lógica |
| `extrator/conversor.py` | localiza e executa o ODA File Converter | leitura de DXF |
| `extrator/leitura.py` | ezdxf → entidades normalizadas; monta os polígonos de AREA | interpretar texto |
| `extrator/parser_texto.py` | texto → números | geometria |
| `extrator/agrupamento.py` | textos empilhados e fragmentos | associação |
| `extrator/associacao.py` | texto ↔ barra | áreas |
| `extrator/areas.py` | ponto-em-polígono, rateio, nomes únicos | pesos |
| `extrator/calculo.py` | peso, perda, categoria, agregações | Excel |
| `extrator/exportacao.py` | escrita do `.xlsx` formatado | cálculo |
| `extrator/pipeline.py` | orquestração e estatísticas | regra de negócio |
| `extrator/log_config.py` | logger de arquivo + console | — |

## Três decisões que sustentam o resto

### 1. Quantidade nunca vem da geometria

Comprimento, quantidade e bitola vêm **só do texto**. A prancha de exemplo
mistura escalas 1:50 e 1:25 na mesma folha — qualquer cálculo baseado no
comprimento desenhado estaria errado pela metade em parte do desenho.

A geometria serve exclusivamente para (a) ligar o texto à barra e (b) decidir
em que região a barra está. A escala é estimada apenas para diagnóstico e
para conferir a quantidade contra a linha de distribuição.

### 2. Tolerâncias em múltiplos da altura do texto

Nenhuma distância é fixa em unidades de desenho. A altura mediana do texto de
cada prancha calibra o raio de associação, a tolerância de agrupamento, o
comprimento mínimo de barra e a área mínima de polígono. O mesmo
`config.yaml` serve para prancha em metro, centímetro ou milímetro.

### 3. Nada desaparece em silêncio

Todo caminho de descarte tem uma saída registrada: texto sem padrão, barra
sem área, associação com score alto, polígono aberto, layer fora do filtro
que contém texto com cara de armadura. Um erro visível vale mais que um
número errado com aparência de certo.

## Performance (milhares de entidades)

- **`STRtree`** na associação texto↔barra e no ponto-em-polígono: consulta
  O(log n). Na prancha de exemplo, 696 textos × 2.268 barras seriam ~1,6
  milhão de comparações na força bruta.
- **Grid hashing** no agrupamento (célula = tolerância): cada texto só é
  comparado com as 9 células vizinhas. Linear, não O(n²).
- Barras **simplificadas** (Douglas-Peucker) antes de entrar no índice —
  importante em desenhos com splines.
- Agregações em `pandas` (`groupby`), não em laços Python.
- Conversão DWG chamando o ODA **uma vez por pasta**, não por arquivo.
