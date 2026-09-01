# Extrator de Aço

Levantamento automático de armadura a partir de plantas de laje em **DWG/DXF**,
com o quantitativo **separado por regiões** delimitadas na layer `AREA` do
próprio desenho.

Feito para volume alto: uma laje que ocupa várias pranchas, com milhares de
posições. Índice espacial (`STRtree`) em vez de varredura O(n²).

> **Antes de confiar nos números, leia [PREMISSAS.md](PREMISSAS.md).**
> Ele lista o que foi verificado no desenho real, o que é suposição, e —
> principalmente — **onde a leitura automática pode falhar**.

---

## Estado atual

Calibrado e validado contra uma prancha real do Eberick/AltoQi
(`Prancha Exemplo Aco.dxf`, laje nervurada, 8.557 entidades):

| Métrica | Resultado |
|---|---|
| Textos de armadura lidos | 640 |
| Posições interpretadas | 425 → **455 posições** (30 textos trazem duas) |
| Ruído descartado (cotas de dobra) | 215 |
| **Textos não interpretados** | **0** |
| Associação texto↔barra | 422 ok · 0 duvidosas · 3 sem barra |
| Área montada a partir de 4 LINEs soltas | ✅ |
| Barras cortadas pelo contorno | 16 → `FORA_DO_ESCOPO`, sem alerta |
| Inconsistências que exigem ação | **0 erros · 3 alertas** |
| Tempo | ~5 s |
| Testes | **97 passando** |

**Conferência independente contra a tabela de aço do próprio DWG:**
Ø8,0 → 1.589,3 m extraídos vs 1.589,3 m na tabela (**exato**).

---

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Para ler arquivos `.dwg` — ODA File Converter

O `ezdxf` **não lê DWG**. Instale o conversor gratuito da Open Design Alliance:

1. Baixe em <https://www.opendesign.com/guestfiles/oda_file_converter>
   (versão Windows 64-bit; pede um e-mail)
2. Instale com as opções padrão — o programa encontra o executável sozinho

Confira a instalação:

```bash
python app.py --checar-oda
```

Se instalou em outro lugar, aponte no `config.yaml`:

```yaml
conversao:
  caminho_oda: "D:/Programas/ODA/ODAFileConverter.exe"
```

**Alternativa sem instalar nada:** exporte as pranchas como DXF pelo próprio
AutoCAD/Eberick (*Salvar como → DXF 2013+*). O processamento é idêntico.

---

## Uso

### Linha de comando

```bash
python app.py --input pranchas/ --output resultado.xlsx
```

Um arquivo só:

```bash
python app.py --input "Prancha Exemplo Aco.dxf" --output quantitativo.xlsx
```

Opções:

| Flag | Efeito |
|---|---|
| `--input`, `-i` | arquivo DWG/DXF **ou pasta** (lote) |
| `--output`, `-o` | `.xlsx` de saída |
| `--config`, `-c` | outro `config.yaml` |
| `--projeto` | nome do projeto, usado como prefixo das abas (padrão: nome do arquivo, ou da pasta em lote) |
| `--criterio` | `maior_parte` (padrão), `centroide`, `proporcional` ou `fora_do_escopo` |
| `--perda` | sobrescreve a perda (ex.: `--perda 0.15`) |
| `--sem-abas-area` | só o resumo geral |
| `--diagnostico` | lê e relata, **sem gerar Excel** — use para calibrar o config |
| `--checar-oda` | verifica o conversor e sai |
| `--log-nivel` | `DEBUG` mostra cada decisão do parser |

### Interface gráfica

```bash
python -m streamlit run streamlit_app.py
```

Envio de arquivos ou pasta, ajuste de perda e critério na hora, tabelas na
tela e download do `.xlsx`.

### Testes

```bash
python -m pytest -q
```

---

## O que sai no Excel

| Aba | Conteúdo |
|---|---|
| **RESUMO GERAL** | tabela mãe: `Posição · Bitola · Quantidade · Comp. unitário · Comp. total · Peso · Peso c/ perda · Categoria`, com **subtotal por bitola**, total geral e quebra por categoria (CA-50/CA-60) |
| **uma aba por TRECHO** | **uma única aba por trecho**, com o aço separado internamente por **sentido** (X horizontal / Y vertical), cada seção com seus subtotais por bitola, o TOTAL DO TRECHO e um RESUMO POR SENTIDO |
| **COMPARAÇÃO FINAL** | tabela mestre × total nos trechos, com a **eficácia** por bitola e no total, onde está o aço que ficou de fora e o peso por trecho |
| **FORA_DO_ESCOPO** | barras **cortadas pelo contorno** da AREA: atravessam a divisa, então não pertencem integralmente a nenhum trecho. Não geram alerta — é situação normal de projeto. Continuam no total geral |
| **SEM_AREA** | armadura inteiramente fora de qualquer polígono — nunca some do total |
| **VERIFICAÇÃO** | (1) soma das áreas × tabela mãe, por bitola; (2) consumo × limite máximo, com semáforo 🟩 dentro / 🟨 próximo / 🟥 excedido, e % consumido |
| **INCONSISTÊNCIAS** | textos não interpretados, barras sem área, textos sem geometria, áreas sobrepostas/abertas, associações duvidosas — **com o handle da entidade para localizar no AutoCAD** — mais as estatísticas do processamento |

Cabeçalho congelado, autofiltro, colunas dimensionadas e casas decimais
consistentes em todas as abas.

**Nome das abas:** todas recebem o nome do projeto como prefixo —
`Obra X - RESUMO`, `Obra X - AREA-01`. O nome vem do arquivo DXF (ou da
pasta, em lote) e pode ser trocado com `--projeto`. Como o Excel limita a
aba a 31 caracteres, nomes longos são cortados **uma única vez**, igual em
todas as abas, e os rótulos fixos ganham forma curta (`RESUMO`, `VERIFIC`,
`INCONSIST`). Nome de projeto com até ~12 caracteres cabe inteiro.

### Trechos: uma layer por trecho

O modo recomendado é desenhar **cada trecho na sua própria layer**, com o
nome que você quer ver na aba:

```
TRECHO 01, TRECHO 02, TRECHO 03...
```

O nome da layer **vira o nome do trecho e o nome da aba**. A poligonização é
feita layer a layer, então contornos de trechos vizinhos que se encostam
nunca se fundem num polígono só. O contorno pode ser polilinha fechada
**ou** linhas soltas — os dois funcionam.

Continua valendo o modo antigo (uma layer `AREA` com várias regiões): aí o
nome vem do texto interno ou vira `AREA-01`, `AREA-02`...

### Eficácia de cobertura

A aba **COMPARAÇÃO FINAL** mede:

```
eficácia = peso atribuído a trechos / peso total extraído
```

É o indicador de que **todos os trechos foram desenhados**. Verde a partir
de 100%, amarelo a partir de 96%, vermelho abaixo disso (`limites.eficacia_minima`
e `limites.eficacia_meta`). O que faltar aparece discriminado entre
`SEM_AREA` (nenhum contorno cobre) e `FORA_DO_ESCOPO` (a barra atravessa a
divisa), com a ação para corrigir cada caso.

### Barra que cruza a divisa entre trechos

Padrão: **`maior_parte`** — a barra **inteira** vai para o trecho que
contém **o maior comprimento** dela. Nada se perde: basta a barra encostar
em um trecho para ser contada nele por completo. É o critério de "incluir
tudo", que leva a eficácia a 100% quando o projeto está todo delimitado.

Não confunda com `centroide`: aquele usa o **ponto médio**, que pode cair
do lado errado. Numa barra 80% dentro de A cujo ponto médio caia em B, o
`centroide` manda tudo para B; o `maior_parte` acerta e manda para A.

| Critério | O que faz | Quando usar |
|---|---|---|
| **`maior_parte`** (padrão) | barra inteira para o trecho com maior comprimento dela | medição normal — inclui tudo |
| `centroide` | barra inteira para o trecho do ponto médio | compatibilidade |
| `proporcional` | rateia o peso pelo comprimento em cada trecho | quando o rateio físico importa |
| `fora_do_escopo` | não conta em trecho nenhum; vai para `FORA_DO_ESCOPO` | medição conservadora — só o que está 100% dentro |

Só vai para `SEM_AREA` a barra que **não toca nenhum trecho** — aí falta
contorno mesmo.

Cada aba de resumo traz abaixo um bloco **DETALHAMENTO**, com uma linha por
texto lido: handle, coordenadas, layer, texto original e `score` da
associação. É por ele que se confere uma leitura suspeita.

---

## Configuração — `config.yaml`

Todas as regras que mudam de escritório para escritório estão lá, comentadas.
Os blocos marcados `[REVISAR]` são os que você deve conferir primeiro:

| Seção | O que controla |
|---|---|
| `layers` | **o mais importante** — quais layers têm texto, barra e AREA, e quais ignorar (a tabela de aço do desenho **precisa** estar ignorada, senão conta em dobro) |
| `parser.padroes` | as regex, avaliadas em ordem — a primeira que casa vence |
| `parser.substituicoes` | `%%c` → `Ø` e outros códigos do AutoCAD |
| `parser.ignorar_textos` | ruído conhecido (cotas de dobra, escalas, títulos) |
| `calculo.peso_linear` | tabela NBR 7480 (kg/m), editável |
| `calculo.perda_percentual` | perda, padrão 10% |
| `areas.criterio_divisa` | o que fazer com a barra cortada pelo contorno: `fora_do_escopo` (padrão), `centroide` ou `proporcional` |
| `areas.fonte_nome` | de onde vem o nome do trecho — `nome_layer` primeiro |
| `sentido` | faixa angular de cada sentido e os rótulos das seções |
| `limites.eficacia_minima` / `eficacia_meta` | 96% e 100% |
| `limites.por_area` | limites em kg para a aba VERIFICAÇÃO |

### Tolerâncias são auto-calibradas

Distâncias **não** são dadas em unidades de desenho, e sim em **múltiplos da
altura mediana do texto**, medida em cada prancha. O mesmo `config.yaml`
funciona em prancha desenhada em metro, centímetro ou milímetro — e em
prancha que **mistura escalas** (1:50 e 1:25 na mesma folha, como a de
exemplo).

### Limites por planilha

Em vez de escrever no YAML:

```yaml
limites:
  arquivo_limites: "limites.xlsx"
```

Planilha com colunas `area | bitola | limite_kg` (bitola vazia = limite total
da área).

---

## Como adaptar a um padrão novo de texto

1. Rode em modo diagnóstico:
   ```bash
   python app.py --input prancha.dxf --diagnostico --log-nivel DEBUG
   ```
2. Veja em `extrator_aco.log` quais textos caíram em
   `TEXTO_NAO_INTERPRETADO`.
3. Acrescente um padrão em `parser.padroes`, usando os grupos nomeados
   `quantidade`, `posicao`, `bitola`, `espacamento`, `comprimento`,
   `comprimento_max`, `observacao`.
4. **Coloque padrões mais específicos antes dos mais genéricos** — o primeiro
   que casar vence. (Um padrão sem espaçamento colocado antes de um com
   espaçamento engoliria o `C/15` como observação.)
5. Rode `python -m pytest -q` para garantir que não quebrou os formatos que
   já funcionavam.

---

## Arquitetura

```
conversão → leitura → parser → agrupamento → associação
         → classificação por área → cálculo → exportação
```

Detalhes e responsabilidade de cada módulo em [ARQUITETURA.md](ARQUITETURA.md).

```
Extrator de aço/
├── app.py                  CLI
├── streamlit_app.py        interface gráfica
├── config.yaml             toda a configuração
├── PREMISSAS.md            premissas, limitações e riscos  ← LEIA
├── PROMPT_CONFERENCIA.md   texto para auditar o resultado em outro chat
├── ARQUITETURA.md          desenho dos módulos
├── extrator/
│   ├── config.py           validação do YAML (pydantic)
│   ├── modelos.py          estruturas de domínio
│   ├── conversor.py        DWG → DXF (ODA)
│   ├── leitura.py          DXF → entidades + polígonos de AREA
│   ├── parser_texto.py     texto → números
│   ├── agrupamento.py      textos empilhados (grid hashing)
│   ├── associacao.py       texto ↔ barra (STRtree + score)
│   ├── areas.py            ponto-em-polígono e rateio
│   ├── calculo.py          NBR 7480, perda, agregações
│   ├── exportacao.py       Excel formatado
│   ├── pipeline.py         orquestração
│   └── log_config.py       log
└── tests/                  83 testes
```

---

## Princípio de projeto

> **Nada é descartado em silêncio.**

Um texto que o parser não entende, uma barra sem área, uma associação
duvidosa, um polígono aberto, uma layer que ficou de fora do filtro: tudo vai
para a aba `INCONSISTÊNCIAS` com o handle da entidade. Num quantitativo, um
erro visível é muito melhor que um número errado com aparência de certo.

Pelo mesmo motivo, **nenhuma quantidade é calculada a partir da geometria** —
comprimento, quantidade e bitola vêm exclusivamente do texto. A geometria só
liga o texto à barra e responde em que região ela está.
