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

**Não precisa de senha de administrador.** Do jeito que vem, o Python
instala só para o seu usuário. Só uma caixa pede administrador — a
`Install launcher for all users` (em algumas versões, "usar privilégios
de administrador para instalar o py.exe"). Se você não tem a senha,
**desmarque essa** e siga: o programa funciona igual.

Também não precisa de administrador para os passos 3 e 4: as bibliotecas
vão para a pasta `.venv` dentro do projeto, e a tela abre em
`127.0.0.1`, que é o próprio computador (por isso nem o aviso do Firewall
do Windows costuma aparecer). A única exceção é o ODA File Converter, o
conversor de `.dwg`, que em geral exige administrador — sem ele, use os
arquivos `.dxf`.

### Se o Windows bloquear o instalador

Mensagem do tipo **"bloqueado"**, "aplicativos seguros" ou "não é um
aplicativo verificado pela Microsoft": o PC está configurado para só
aceitar programas da Microsoft Store. Duas saídas:

**A mais simples — instale o Python pela própria Store.** Ele está
publicado lá oficialmente pela *Python Software Foundation*. Abra a
Microsoft Store, busque `Python 3.13` (ou 3.12), confira o publicador e
instale. É o mesmo Python, já se registra sozinho e não precisa da caixa
`Add Python to PATH`.

**Ou libere a trava:** Configurações → Aplicativos → Configurações
avançadas de aplicativos → `Escolher onde obter aplicativos` → mude para
`Qualquer lugar`. Às vezes a própria janela do bloqueio já oferece um
botão `Instalar mesmo assim`.

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

**O Windows avisa ao abrir os `.bat`** — é o SmartScreen, porque os
arquivos vieram da internet dentro do ZIP. Clique em `Mais informações` →
`Executar assim mesmo`. São arquivos de texto do próprio projeto; dá para
abrir no Bloco de Notas e ler o que fazem.

**A tela abre mas não muda nada depois de mexer no código** — o Python só
recarrega os arquivos ao reiniciar. Feche a janela preta e abra de novo.

**A página do navegador não abre sozinha** — digite `http://127.0.0.1:8501`
na barra de endereço, com a janela preta aberta.

**Arquivos `.dwg`** só são lidos se o ODA File Converter estiver
instalado neste PC (veja o `README.md`). Sem ele, use os `.dxf` — a
barra lateral avisa quando ele não é encontrado.
