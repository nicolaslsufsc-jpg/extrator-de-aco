# Texto para conferência final em outro chat do Claude

Abra um **chat novo do Claude**, anexe os arquivos indicados e cole o texto
que está dentro do bloco abaixo (da primeira à última linha).

**Anexe junto:**

1. O `.xlsx` gerado pelo Extrator de Aço.
2. A **tabela de resumo de aço do projeto** — PDF da prancha, print da
   tabela, planilha do Eberick ou o memorial. É a referência da conferência;
   sem ela o Claude só consegue checar coerência interna.
3. *(Opcional)* O `extrator_aco.log` da mesma execução.

---

```
Você é um conferente de quantitativo de estruturas de concreto armado.
Vou te dar duas fontes do MESMO levantamento de aço e preciso de uma
auditoria numérica, não de um resumo.

FONTE A — planilha gerada por um extrator automático de DWG/DXF (anexo
.xlsx). Estrutura das abas:
  - "<PROJETO> - RESUMO GERAL": tabela mestre, todo o aço da(s) prancha(s).
    Colunas: Posição | Bitola (mm) | Quantidade | Comprimento unitário (cm)
    | Comprimento total (m) | Peso (kg) | Peso com perda (kg) | Categoria.
    Tem subtotal por bitola e TOTAL GERAL.
  - "<PROJETO> - TRECHO XX": uma aba por trecho da obra, com o aço separado
    internamente por sentido (SENTIDO X horizontal / SENTIDO Y vertical),
    cada seção com seus próprios subtotais por bitola.
  - "<PROJETO> - FORA_DO_ESCOPO": só existe se o critério conservador
    estiver ligado. Com o padrão ("maior_parte"), a barra que cruza a divisa
    é contada inteira no trecho onde ela mais está, e esta aba não aparece.
  - "<PROJETO> - SEM_AREA": aço fora de todos os contornos.
  - "<PROJETO> - COMPARAÇÃO FINAL": eficácia = peso dentro de trechos /
    peso total extraído.
  - "<PROJETO> - INCONSISTÊNCIAS": o que o extrator não conseguiu resolver.

FONTE B — a tabela de resumo de aço do projeto (anexo). É a REFERÊNCIA.

COMO O EXTRATOR CALCULA (para você reproduzir e checar):
  comprimento_total (m) = quantidade × comprimento_unitário (cm) / 100
  peso_líquido (kg)     = comprimento_total (m) × peso_linear (kg/m)
  peso_com_perda (kg)   = peso_líquido × (1 + perda)
  Peso linear NBR 7480 (kg/m): 5,0=0,154 · 6,3=0,245 · 8,0=0,395 ·
  10,0=0,617 · 12,5=0,963 · 16,0=1,578 · 20,0=2,466 · 25,0=3,853 ·
  32,0=6,313. Categoria: Ø ≤ 6,0 = CA-60; Ø ≥ 6,3 = CA-50.

LIMITAÇÕES CONHECIDAS DO EXTRATOR — considere antes de apontar erro:
  1. Barras com comprimento em faixa ("C=880-900") entram pela MÉDIA. Isso
     subestima de 1% a 2% nas bitolas afetadas. Estão marcadas na aba
     INCONSISTÊNCIAS como COMPRIMENTO_VARIAVEL.
  2. Malha/tela de EPS declarada só como nota de texto NÃO é extraída.
     Se a Fonte B tiver essa linha, separe-a antes de comparar.
  3. Uma laje pode ocupar várias pranchas. Se a Fonte A cobre menos
     pranchas que a Fonte B, a diferença é de escopo, não erro de leitura.

O QUE EU QUERO, NESTA ORDEM:

1. TABELA DE COMPARAÇÃO POR BITOLA
   Uma linha por bitola, com: peso na Fonte B | peso na Fonte A |
   diferença em kg | diferença em % | veredito.
   Veredito: OK (|dif| ≤ 2%), ATENÇÃO (2% a 5%), DIVERGENTE (> 5%).
   Feche com a linha TOTAL e o percentual de aderência global
   (Fonte A / Fonte B × 100).

2. CRITÉRIO DE APROVAÇÃO
   Aderência ≥ 96% = aprovado. Abaixo disso, reprovado.
   Diga explicitamente APROVADO ou REPROVADO e o número.

3. ONDE ESTÁ A DIFERENÇA
   Para cada bitola com diferença acima de 2%, aponte a causa mais
   provável, escolhendo entre: comprimento variável · posição não lida ·
   escopo de pranchas · malha não extraída · erro de bitola · outra.
   Cite as posições específicas quando conseguir identificá-las.

4. COERÊNCIA INTERNA DA FONTE A (não depende da Fonte B)
   a) A soma das abas de trecho + FORA_DO_ESCOPO + SEM_AREA bate com o
      TOTAL GERAL do RESUMO GERAL? Mostre os números.
   b) Em 5 linhas escolhidas por você, refaça a conta
      quantidade × comprimento / 100 × peso_linear e confirme o peso.
   c) A soma dos subtotais por bitola bate com o TOTAL GERAL?
   d) Dentro de cada aba de trecho, a soma das seções de sentido bate com
      o TOTAL DO TRECHO?

5. EFICÁCIA DE COBERTURA DOS TRECHOS
   Leia a aba COMPARAÇÃO FINAL. Se a eficácia estiver abaixo de 96%, diga
   quanto peso está em SEM_AREA e em FORA_DO_ESCOPO e o que precisa ser
   feito no CAD para subir (desenhar contorno faltante, ajustar contorno
   que corta barra ao meio).

6. LISTA DE AÇÕES
   No máximo 5 itens, em ordem de impacto em kg, do que eu preciso
   conferir ou corrigir no desenho para fechar em 100%.

REGRAS:
- Trabalhe com os números dos anexos. Não estime o que não conseguir ler:
  diga "não consegui ler" e siga.
- Toda diferença apontada vem com o valor em kg E em %.
- Não reescreva a planilha nem proponha refazer o levantamento.
- Português do Brasil, vírgula decimal, unidades sempre explícitas.
```

---

## Variação: conferir sem ter a tabela do projeto

Se você não tiver a Fonte B em mãos, troque os itens 1 a 3 por:

```
Não tenho a tabela de referência do projeto. Faça só a auditoria de
coerência interna (item 4), a eficácia de cobertura (item 5) e a lista de
ações (item 6). Além disso, aponte na aba RESUMO GERAL as 10 posições de
maior peso e diga, para cada uma, se os números são plausíveis para uma
laje de concreto armado — sinalizando comprimento unitário, quantidade ou
espaçamento que fujam do usual.
```
