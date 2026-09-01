# PREMISSAS E LIMITAÇÕES — Extrator de Aço

> **Leia antes de confiar em qualquer número.**
>
> Este documento foi **calibrado com a prancha real** `Prancha Exemplo Aco.dxf`
> (Eberick/AltoQi — laje nervurada, armadura longitudinal inferior, 8.557
> entidades, 640 textos de armadura). O que está marcado ✅ foi **verificado
> no arquivo**; o que está marcado ⚠️ é **suposição** que muda de escritório
> para escritório.
>
> Tudo é ajustável em `config.yaml` — nenhuma regra está presa no código.

---

## 1. Formato do texto de armadura

### 1.1 O que foi encontrado na prancha ✅

O Eberick grava a posição em **um único `TEXT`**, sem espaços, usando o
código de controle do AutoCAD `%%c` (ou `%%C`) para o símbolo Ø:

| Formato real | Ocorrências | Significado |
|---|---:|---|
| `1N100-%%c12.5 C=1160` | 278 | qtd 1, pos 100, Ø12,5, comp 1160 cm |
| `159N1-%%c10c/15 C=880` | 43 | com espaçamento `c/15` |
| `25N3-%%C6.3c/11 C=111` | 39 | `%%C` maiúsculo |
| `2N50-%%c10 C=300+2N51-%%c10 C=250` | 30 | **duas posições no mesmo texto** |
| `159N1-%%c10c/15 C=880-900` | 22 | **comprimento variável (faixa)** |
| `11N215B-%%C16 C=100` | 10 | posição com sufixo alfabético |
| `19`, `2375` (números soltos) | 215 | **não são posições** — cotas de dobra |

**Resultado da calibração: 640 textos lidos, 425 posições interpretadas,
215 descartados como ruído, 0 falhas de interpretação.**

### 1.2 Premissas assumidas

| # | Premissa | Status | Onde ajustar |
|---|---|---|---|
| P1.1 | Cada posição cabe em **uma linha** de texto | ✅ verificado | `parser.padroes` |
| P1.2 | Ordem: quantidade → posição → bitola → espaçamento → comprimento | ✅ verificado | `parser.padroes` |
| P1.3 | Posição começa com `N`, aceita sufixo (`N215B`) | ✅ verificado | `parser.padroes` |
| P1.4 | `%%c`, `%%C`, `Ø`, `ø`, `φ`, `Φ`, `⌀`, `D`, `#` são o mesmo símbolo | ✅ verificado | `parser.substituicoes` |
| P1.5 | Vírgula e ponto são ambos separador decimal | ✅ suportado | `parser.decimal_virgula` |
| P1.6 | Sem quantidade ⇒ 1 barra; sem `c/` ⇒ barra isolada | ✅ verificado | `parser.quantidade_padrao` |
| P1.7 | `C=` está em **centímetros**, bitola em **milímetros** | ✅ verificado | `unidades.*` |
| P1.8 | **`+` separa duas posições** no mesmo texto | ✅ verificado | `parser.separadores_multiplas_posicoes` |
| P1.9 | Texto que é só um número é cota de dobra, não posição | ✅ verificado | `parser.ignorar_textos` |
| P1.10 | Texto não interpretado **nunca é descartado** — vai para `INCONSISTENCIAS` | ✅ garantido por teste | — |

### 1.3 ⚠️ RISCO ALTO — comprimento variável (`C=880-900`)

**22 posições da prancha de exemplo têm comprimento em faixa.** O programa
adota a **média** e sinaliza cada uma como `COMPRIMENTO_VARIAVEL`.

O Eberick calcula o comprimento real barra a barra, o que a planta não
informa. Medindo contra a tabela do próprio DWG, o erro dessa estimativa é:

| Bitola | Tabela do DWG | Extraído | Diferença |
|---|---:|---:|---:|
| Ø8,0 | 1.589,3 m | 1.589,3 m | **0,0%** (sem barra variável) |
| Ø6,3 | 3.436,7 m | 3.374,9 m | −1,8% |
| Ø10,0 | 12.974,4 m | 12.899,7 m | −0,6% |

**Conclusão: onde não há comprimento variável, a extração é exata. Onde há,
subestima ~1 a 2%.** Para orçamento com perda de 10% isso está coberto; para
compra fechada, confira as posições marcadas na aba `INCONSISTENCIAS`.

### 1.4 ⚠️ Não é lido automaticamente

- **Malha de tela / armadura de EPS**: a prancha traz
  `MALHA DE 2Ø5.0 SOBRE CADA EPS — TRASPASSE DE 30cm` (5.170 barras,
  **9.306 kg**) apenas como **anotação em texto livre na tabela**, sem
  geometria de barra associada. **Esse aço NÃO é extraído** e precisa ser
  lançado à mão.
- **Observações que alteram o quantitativo** (`(2ª camada)`, `alternadas`)
  são preservadas na coluna de observação, mas **não mudam o cálculo**.

---

## 2. Unidades e escala do desenho

### 2.1 O que foi encontrado ✅

- `$INSUNITS = 4` (milímetros) no cabeçalho — **mas isso não descreve a
  realidade do arquivo**.
- Medindo o comprimento **desenhado** das barras contra o `C=` **declarado**:
  **1 unidade de desenho ≈ 50 cm reais** (prancha plotada em 1:50).
- A prancha **mistura escalas**: os textos indicam `ESC. 1:50` na planta e
  `ESC. 1:25` nos detalhes, na mesma folha.

### 2.2 Decisão de projeto que decorre disso

> **Nenhuma quantidade é calculada a partir da geometria.**
> Comprimento, quantidade e bitola vêm **exclusivamente do texto**.
> A geometria serve só para (a) ligar texto à barra e (b) o teste
> ponto-em-polígono.

Isso torna o resultado **imune ao erro de escala** — que seria catastrófico
numa prancha com duas escalas.

### 2.3 Tolerâncias auto-calibradas ✅

As tolerâncias **não** são dadas em unidades de desenho, e sim em
**múltiplos da altura mediana do texto**, medida em cada prancha
(0,18 unidades na prancha de exemplo):

| Tolerância | Múltiplo | Valor efetivo no exemplo |
|---|---|---|
| Agrupamento de textos empilhados | 3 × altura | 0,54 un. |
| Raio de busca da barra | 12 × altura | 2,16 un. |
| Comprimento mínimo de barra | 2 × altura | 0,36 un. |
| Área mínima de polígono | 100 × altura² | 3,24 un.² |

O mesmo `config.yaml` funciona em prancha desenhada em metro, centímetro ou
milímetro, sem reconfigurar nada.

### 2.4 Outras premissas

| # | Premissa | Status |
|---|---|---|
| P2.1 | Armadura está no **Model Space** (Layout só tem viewports) | ✅ verificado |
| P2.2 | Blocos são explodidos virtualmente até 3 níveis, em WCS | ⚠️ suposição |
| P2.3 | ⚠️ **Pranchas em coordenadas sobrepostas** (cada uma na origem) fariam áreas de pranchas diferentes colidirem. **Mitigado**: cada prancha é classificada só contra as suas próprias áreas | ✅ implementado |

---

## 3. Layers

### 3.0 Trechos: uma layer por trecho (modo recomendado)

Cada trecho desenhado na sua própria layer — `TRECHO 01`, `TRECHO 02` — e o
**nome da layer vira o nome do trecho e da aba**.

| # | Premissa | Status |
|---|---|---|
| P3.0a | Layers que casam com `TRECHO*` delimitam trechos | ✅ testado |
| P3.0b | A poligonização é feita **layer a layer** — contornos vizinhos que se encostam não se fundem | ✅ testado |
| P3.0c | Layer genérica (`AREA`, `0`, `TRECHO` sem número) **não** nomeia trecho: cai para texto interno ou sequencial | ✅ testado |
| P3.0d | Polilinha fechada e linhas soltas funcionam igual | ✅ testado |

⚠️ **Se o contorno de um trecho não fechar, aquele trecho não existe no
relatório** e toda a sua armadura cai em `SEM_AREA`. Reportado como
`AREA_NAO_FECHADA` — confira o número de trechos encontrados no log contra
o número de layers que você desenhou.

### 3.1 O que foi encontrado ✅ (44 layers na prancha)

| Layer | Conteúdo | Tratamento |
|---|---|---|
| `AREA` | **4 LINEs soltas** formando um retângulo | ✅ polígono montado por poligonização |
| `ARR_LONG_INF_TXT` | 640 TEXT — as posições | ✅ lida |
| `ARR_LONG_INF` | 479 polilinhas — corpo das barras | ✅ lida |
| `ARR_L_I_IG_LINHA` | 3.752 entidades — barras repetidas da distribuição | ✅ lida |
| `ARR_L_I_IG_DIST` | 56 TEXT — extensão da distribuição em cm | ✅ usada para conferência |
| `TEXTO_TABELAS`, `TABFER`, `TABELAS` | **a tabela de resumo de aço do próprio desenho** | ✅ **ignorada** (senão contaria em dobro) |
| `A-TXT-*`, `DT-*`, `FO-*` | detalhes típicos e legendas | ✅ ignorada |

### 3.2 ⚠️ RISCO ALTO — a layer `AREA` não tem polilinha fechada

Na prancha de exemplo a região é composta por **4 `LINE` separadas**, não por
uma `LWPOLYLINE` fechada. O programa monta o polígono automaticamente
(`areas.montar_de_segmentos: true`) e **marca a área como
`montado_de_segmentos`**.

**Se um único segmento estiver faltando ou sem encostar no vizinho, o
contorno não fecha e a área inteira desaparece** — toda a armadura vai para
`SEM_AREA`. Isso é reportado como `AREA_NAO_FECHADA`, mas **confira sempre o
número de áreas encontradas no log** contra o que você desenhou.

### 3.3 Rede de segurança contra filtro apertado ✅

Se um texto **com formato de armadura** aparecer numa layer que não está em
`layers.texto_armadura`, o programa **não o ignora em silêncio**: reporta
`TEXTO_EM_LAYER_NAO_LIDA` na aba de inconsistências, com exemplo e contagem.

Na prancha de exemplo isso apontou corretamente 2 textos em `A-TXT-FT`
(`N1-8Ø16.0 C=180`) — que são de **detalhe típico**, não da laje, e portanto
devem mesmo ficar de fora.

---

## 4. Regras de cálculo

| # | Premissa | Status | Onde ajustar |
|---|---|---|---|
| P4.1 | `Quantidade = a do texto`. O `c/` **não** recalcula nada | ✅ padrão | `calculo.recalcular_quantidade` |
| P4.2 | `Comprimento total (m) = qtd × C= / 100`; o `C=` já inclui dobras e ganchos | ✅ verificado | `unidades.comprimento_texto` |
| P4.3 | Peso linear NBR 7480 | ✅ conferido contra o DWG (erro < 0,2%) | `calculo.peso_linear` |
| P4.4 | Ø ≤ 6,0 ⇒ CA-60; Ø ≥ 6,3 ⇒ CA-50 | ✅ igual à tabela do DWG | `calculo.categoria_por_bitola` |
| P4.5 | Perda de 10%, em **coluna separada** do peso líquido | ✅ | `calculo.perda_percentual` |

### 4.1 Conferência cruzada da quantidade ✅

Quando existe a linha de distribuição, o programa confere
`quantidade = ceil(extensão / espaçamento)`. Validado em 8 posições:

| Posição | Extensão | Espaçamento | Calculado | Texto |
|---|---:|---:|---:|---:|
| N1 | 2375 cm | 15 | 159 | 159 ✓ |
| N5 | 350 cm | 10 | 35 | 35 ✓ |
| N7 | 375 cm | 10 | 38 | 38 ✓ |
| N6 | 350 cm | 18 | 20 | 20 ✓ |

Divergência acima de 15% vira `DIVERGENCIA_QUANTIDADE`.

---

## 5. Separação por AREA — casos limite

| Caso | Tratamento padrão | Alternativa |
|---|---|---|
| Barra dentro de um trecho | vai toda para ele | — |
| **Barra cruzando a divisa** | `maior_parte` (PADRÃO): a barra **inteira** vai para o trecho que contém **o maior comprimento** dela. Nada é descartado | `centroide` — usa o ponto médio · `proporcional` — rateia pelo comprimento · `fora_do_escopo` — não conta em trecho nenhum |
| Barra que **encosta** num trecho mas está majoritariamente fora | conta **inteira** no trecho que ela toca (critério "incluir tudo") | trocar para `fora_do_escopo` se quiser medição conservadora |
| Barra que **não toca nenhum trecho** | categoria **`SEM_AREA`** (severidade INFO). É onde falta contorno | — |
| **Áreas sobrepostas** | contada na **maior** área (ordem estável, independente da ordem de leitura); sobreposição reportada como ERRO | — |
| Polilinha aberta | fechada automaticamente se a folga < 2% do perímetro; senão descartada e reportada | `leitura.tolerancia_fechamento_rel` |

Na prancha de exemplo, **16 posições (994,8 kg com perda)** atravessam o
contorno. Com o padrão `maior_parte` elas são contadas inteiras no trecho
onde estão em maior parte — a eficácia sobe de 45,6% para 52,6% só com
isso. Com `fora_do_escopo` ficariam de fora.

**Garantia testada:** mudar o critério **redistribui** o aço entre áreas,
mas **nunca altera o total geral** (`test_criterio_proporcional_nao_altera_o_total_geral`),
e a soma das áreas sempre fecha com a tabela mãe (aba `VERIFICACAO`).

### 5.1 ⚠️ LIMITAÇÃO IMPORTANTE — armadura distribuída na divisa

Uma posição distribuída (`159N1-Ø10c/15 C=880`, 159 barras ao longo de
23,75 m) é classificada por **um único ponto**. Se a distribuição atravessar
a divisa entre dois trechos, **as 159 barras vão todas para um lado só**.

O critério `proporcional` rateia apenas ao longo do **comprimento da barra**,
não ao longo da **direção de distribuição**.

**Consequência prática:** posicione os polígonos da layer `AREA` de modo a
**não cortar uma faixa de distribuição ao meio**. Onde isso for inevitável,
confira manualmente as posições distribuídas listadas no bloco
DETALHAMENTO de cada aba.

---

## 6. Limites de consumo (aba VERIFICAÇÃO)

| # | Premissa | Onde ajustar |
|---|---|---|
| P6.1 | Limites em kg, por área, no total e/ou por bitola | `limites.por_area` ou `limites.arquivo_limites` |
| P6.2 | Verde < 90% · amarelo 90–100% · vermelho > 100% | `limites.percentual_alerta` |
| P6.3 | Compara o **peso com perda** contra o limite | `limites.base_comparacao` |
| P6.4 | Área sem limite declarado aparece como `NAO VERIFICADO` | — |

---

## 7. ONDE A LEITURA AUTOMÁTICA PODE FALHAR — conferência humana

Todos os itens abaixo aparecem na aba `INCONSISTENCIAS` com **handle** da
entidade (para localizar no AutoCAD) e coordenadas.

| # | Risco | Gravidade | Como conferir |
|---|---|---|---|
| 1 | **Comprimento variável** (`C=880-900`) estimado pela média | ALTA | filtrar `COMPRIMENTO_VARIAVEL`; erro medido: −1 a −2% |
| 2 | **Malha de EPS / tela** não é extraída (9.306 kg no exemplo) | ALTA | lançar à mão a partir da nota do desenho |
| 3 | **Área não fechou** — toda a armadura foi para `SEM_AREA` | ALTA | conferir `areas encontradas` no log |
| 4 | **Áreas sobrepostas** — subcontagem silenciosa na área menor | ALTA | filtrar `AREA_SOBREPOSTA` |
| 5 | **Distribuição cruzando divisa** — vai inteira para um lado | MÉDIA | ver 5.1 acima |
| 6 | **Texto ligado à barra errada** entre barras paralelas | MÉDIA | ordenar o DETALHAMENTO por `Score associacao` (maior = pior) |
| 7 | **Barras empilhadas** trocadas entre si | MÉDIA | não muda o total; muda a divisão entre áreas |
| 8 | **Tabela de resumo do DWG** contada em dobro | ALTA se ocorrer | confira se a layer da sua tabela está em `layers.ignorar` |
| 9 | **Pranchas duplicadas na pasta** (v1 e v2) são somadas | ALTA se ocorrer | não há detecção de versão — limpe a pasta antes |
| 10 | **Conversão DWG→DXF falhou** (proxies/objetos customizados) | ALTA | confira a contagem de entidades no log |
| 11 | Uma laje ocupa **várias pranchas** | INFORMATIVO | processe a pasta inteira em lote, não prancha a prancha |

### 7.1 Nota sobre a prancha de exemplo

O total extraído (**12.912,7 kg líquidos**) é **menor** que o total da tabela
de resumo do próprio DWG (19.960 kg CA-50). A diferença está concentrada em
Ø12,5 e Ø16 e **não é erro de leitura** — 100% dos textos da planta foram
interpretados. A explicação é que a tabela do desenho resume **o elemento
inteiro**, que se estende por **mais de uma prancha**, enquanto o arquivo
fornecido contém apenas a armadura longitudinal inferior desenhada nele.

**Processe a pasta com todas as pranchas da laje para fechar com a tabela.**
