# Como rodar o Extrator de Aço em outro computador

Tudo que o programa precisa está no GitHub, inclusive a prancha de
referência. Não é preciso levar pen drive nem copiar nada do PC antigo.

> **Endereço do projeto**
> https://github.com/nicolaslsufsc-jpg/extrator-de-aco

---

## Passo 1 — instalar o Python (uma vez só, por PC)

Baixe em https://www.python.org/downloads/ e, **na primeira tela do
instalador, marque a caixa `Add Python to PATH`**. É a caixa que quase
todo mundo esquece; sem ela nada mais funciona.

## Passo 2 — trazer o projeto para o PC

Escolha **um** dos dois caminhos:

**A) Só quero usar o programa** — baixe o ZIP:
abra o endereço do projeto, botão verde `Code` → `Download ZIP`, e
extraia numa pasta sua (por exemplo `C:\Extrator de Aco`).

**B) Quero também mexer no código e salvar na nuvem** — instale o Git
(https://git-scm.com/download/win, pode aceitar tudo como vem) e depois,
na pasta onde quer o projeto, abra o Prompt de Comando e rode:

```bat
git clone https://github.com/nicolaslsufsc-jpg/extrator-de-aco.git
```

Só o caminho B deixa o `SUBIR PARA O GITHUB.bat` funcionar.

## Passo 3 — preparar o PC

Dentro da pasta do projeto, dê **dois cliques** em:

```
INSTALAR NO PC NOVO.bat
```

Ele acha o Python, cria o ambiente `.venv` deste computador, instala as
bibliotecas e, no fim, roda a bateria de testes. O `.venv` é de cada PC —
ele não viaja junto com o projeto, por isso este passo se repete em cada
máquina nova.

Terminando com **`PRONTO. Este PC esta preparado.`**, está tudo certo.

## Passo 4 — abrir o programa

Dois cliques em:

```
ABRIR PROGRAMA.bat
```

Abre a tela no navegador, no endereço `http://127.0.0.1:8501`.

**Deixe a janela preta aberta enquanto usa o programa.** Ela é o motor:
fechando, a tela para de responder. Para encerrar, feche a janela.

---

## Conferindo que a leitura está certa

A prancha `SEM NADA.dxf` já vem na pasta do projeto. Jogue ela na tela e
os números têm que bater exatamente com estes:

| | |
|---|---|
| Tabela mestre | 268 linhas, 8.919,5 kg |
| Trechos | 1 (`TRECHO A`) |
| Posições no trecho | 9 |
| Peso líquido | 111,55 kg |
| Peso com perda (10%) | 122,70 kg |

Se algum número sair diferente, a leitura mudou de comportamento — não é
o arquivo que está errado.

---

## Se der problema

**"Nao encontrei Python 3.11 ou mais novo"** — o Python não foi
instalado, ou a caixa `Add Python to PATH` ficou desmarcada. Reinstale
marcando a caixa.

**"Este computador ainda nao foi preparado"** ao abrir o programa —
faltou rodar o `INSTALAR NO PC NOVO.bat` antes.

**A tela abre mas não muda nada depois de mexer no código** — o Python só
recarrega os arquivos ao reiniciar. Feche a janela preta e abra de novo.

**A página do navegador não abre sozinha** — digite `http://127.0.0.1:8501`
na barra de endereço, com a janela preta aberta.

**Arquivos `.dwg`** só são lidos se o ODA File Converter estiver
instalado neste PC (veja o `README.md`). Sem ele, use os `.dxf` — a
barra lateral avisa quando ele não é encontrado.
