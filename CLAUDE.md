# Extrator de Aço

Levantamento de armadura a partir de plantas DXF do Eberick, separado pelos
trechos delimitados no próprio desenho. Saída em `.xlsx` para corte e dobra.

O autor é engenheiro estrutural, não programador. Explique em português, em
termos de projeto (barra, bitola, dobra, trecho), não em termos de código.

---

## REGRAS DO PROJETO — leia antes de mexer em qualquer coisa

### 1. Só existe um arquivo de teste

`C:\Users\nicol\OneDrive\Desktop\SEM NADA.dxf`

**Não use nenhuma outra prancha para testar.** Calibrar em várias plantas
diferentes foi o que fez a leitura andar de lado: um ajuste que melhorava
uma piorava outra e ninguém percebia. A referência única está em
`tests/conftest.py` como `ARQUIVO_REFERENCIA`, e todo teste de arquivo real
usa a fixture `dxf_referencia`.

Números reais desse arquivo, para conferência rápida:

| | |
|---|---|
| Tabela mestre | 268 linhas, 8.919,5 kg |
| Trecho | 1 (`TRECHO A`) |
| Posições no trecho | 9 |
| Peso do trecho | 111,55 kg líquido / 122,70 kg com perda |
| Textos de armadura | 6 (três deles empilhados, rendendo 2 posições cada) |

### 2. Quantidade NUNCA vem da geometria

O desenho mistura escalas 1:50 e 1:25 na mesma prancha. Medir a barra
desenhada para saber quantas são dá errado sempre. A quantidade vem, nesta
ordem:

1. do número escrito no próprio texto (`N264-1Ø10 C=790`);
2. da extensão da distribuição, `ceil(extensão ÷ espaçamento)`, quando o
   texto traz `c/10` mas não traz o número de barras (`extrator/distribuicao.py`);
3. da tabela mestre rateada entre os trechos — só quando o desenho cobre
   boa parte da tabela (ver "recorte" abaixo).

### 3. As dobras vêm das COLUNAS da tabela mestre

O cabeçalho da tabela é:

```
Elemento | Pos. | Diam. | Q. | Dob. | Reta | Dob. | Comp. | Total | CA-50 | CA-60
```

**Célula vazia não existe como texto no DXF** — barra reta simplesmente não
tem a célula `Dob.`. Por isso contar células da esquerda para a direita não
diz em que coluna o número está. Quem diz é o X: o texto da tabela é
alinhado, então o `align_point` é idêntico em toda a coluna.

Nunca volte a deduzir a dobra pelo tamanho da perna ("a maior é a reta").
Isso erra o lado do gancho quando a dobra é grande. Há teste travando isso:
`test_gancho_maior_que_a_reta_nao_troca_de_coluna`.

A soma `Dob. + Reta + Dob. = Comp.` fecha nas 268 linhas do arquivo de
referência — é essa conferência que denuncia leitura deslocada de coluna.

### 4. Recorte não vira pavimento inteiro

O fluxo do autor é apagar do DXF tudo que não pertence ao trecho — outras
barras, desenhos, arquitetura. Então o desenho tem poucas posições e a
tabela mestre continua descrevendo o pavimento todo.

Ratear a tabela em cima de poucas barras seria o pior erro possível (uma
barra desenhada virando centenas). `_usar_gabarito()` em `pipeline.py` mede
a cobertura e, abaixo de `calculo.limiar_recorte`, reporta **o que está
desenhado**. No arquivo de referência a cobertura é 3%.

### 5. Barra que cruza a divisa entre trechos

Vai inteira para o lado onde ela mais está (`areas.criterio_divisa =
"maior_parte"`). Não se descarta aço e não se corta barra em dois.

### 6. A planilha tem três formatos, e o padrão do autor é o enxuto

`saida.modo_enxuto` (ou `--enxuto`) gera **uma aba por trecho** — a lista
de corte e dobra — e **uma aba `CONFERENCIA`**, que responde barra a
barra: esta posição consta na tabela mestre, com o mesmo comprimento
unitário? Não gera `RESUMO GERAL`, `COMPARACAO FINAL` nem
`INCONSISTENCIAS`; todo problema vira **uma observação** no topo da
`CONFERENCIA`.

Na `CONFERENCIA`, **quantidade não reprova nada**. Pela regra 4 o desenho
é um recorte e a tabela descreve o pavimento inteiro, então divergir de
quantidade é o esperado. O que reprova é a identidade da barra: posição,
bitola e comprimento unitário. Teste travando isso:
`test_conferencia_nao_reprova_por_quantidade`.

`modo_limpo` continua existindo (abas de trecho + `RESUMO GERAL` +
`COMPARACAO FINAL`) e o modo completo também. Com os dois ligados, o
enxuto vence.

### 7. Trecho é o nome da layer

Uma layer `TRECHO A` vira o trecho `TRECHO A`. Nomes vindos de layer **nunca**
são desambiguados: se a mesma layer aparecer em dois lugares, é o mesmo
trecho. Já houve bug de `TRECHO A (2)` escondendo 12 toneladas.

---

## Como rodar

```bat
.venv\Scripts\python.exe -m pytest -q
```

```bat
.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true
```

CLI: `.venv\Scripts\python.exe app.py <arquivo.dxf>`

Se o `.venv` não existir (PC novo), rode `INSTALAR NO PC NOVO.bat`.

---

## Armadilhas que já custaram tempo

**Streamlit não recarrega módulo importado.** Depois de mexer em
`extrator/*.py`, mate o processo e suba de novo — recarregar a página não
adianta. Confira que o processo subiu *depois* da última alteração:
comparar `(Get-Process -Id N).StartTime` com o mtime dos fontes.

**Script de patch tem que ter `assert` na âncora.** Um `replace` que não
encontra o texto falha calado e deixa o arquivo velho, dando erro em outro
lugar horas depois.

**O heredoc do Bash come `\\`.** Para escrever script com caminho do Windows,
use a ferramenta Write ou barra normal (`C:/Users/...`), que o Windows aceita.

**Contorno de trecho quase fechado.** Extremos que não coincidem por 1e-13
impedem a poligonização. `_costurar()` em `leitura.py` junta os extremos;
a poligonização é feita **por layer**, senão trechos vizinhos se fundem.

---

## Onde está cada coisa

| Arquivo | Papel |
|---|---|
| `extrator/leitura.py` | DXF → textos e geometrias; costura de contorno |
| `extrator/parser_texto.py` | regex das armaduras (padrão específico antes do genérico) |
| `extrator/tabela_mestre.py` | lê a tabela do projeto; dobras por coluna |
| `extrator/distribuicao.py` | quantidade por extensão ÷ espaçamento |
| `extrator/areas.py` | trechos, ponto-em-polígono, critério de divisa |
| `extrator/rateio.py` | quantidade da tabela distribuída pelos trechos |
| `extrator/pipeline.py` | orquestra; decide a fonte da quantidade |
| `extrator/exportacao.py` | escreve o `.xlsx` (colunas por NOME, não índice) |
| `config.yaml` | tudo configurável: layers, regex, perdas, tolerâncias |

Documentação de fundo: `PREMISSAS.md`, `ARQUITETURA.md`, `README.md`.

---

## O que ainda está pendente

- A pasta `../Extrator de Aco PORTATIL/` está ~1.500 linhas atrás e sem
  `distribuicao.py`. Rodar ela hoje devolve tabela errada.
- `config.yaml` não documenta as chaves novas (`layers.texto_distribuicao`,
  `calculo.recuperar_quantidade_distribuicao`, `raio_extensao_fator`,
  `margem_ambiguidade`, `limiar_recorte`). Os defaults existem no schema.
- `README.md` e `PREMISSAS.md` não mencionam costura de contorno, detecção
  de recorte, dobras por coluna nem recuperação por distribuição.
