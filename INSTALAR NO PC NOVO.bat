@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ==========================================================
echo   EXTRATOR DE ACO - preparar este PC para desenvolvimento
echo ==========================================================
echo.
echo Isto cria o ambiente Python DESTE computador, dentro da
echo pasta .venv. Cada PC tem o seu: ele nao viaja pelo OneDrive.
echo.

REM ---- achar um Python 3.11 ou mais novo -------------------------------
set "PY="
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo [ERRO] Nao encontrei Python 3.11 ou mais novo neste computador.
    echo.
    echo   1. Baixe em  https://www.python.org/downloads/
    echo   2. Na instalacao, MARQUE a caixa "Add Python to PATH"
    echo   3. Rode este arquivo de novo
    echo.
    echo Se voce so quer USAR o programa e nao mexer nele, nao precisa
    echo de nada disso: use a pasta "Extrator de Aco PORTATIL".
    echo.
    pause
    exit /b 1
)

echo Python encontrado: %PY%
%PY% --version
echo.

REM ---- venv herdado de outro PC nao presta ------------------------------
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo O .venv existente veio de outro computador e nao funciona aqui.
        echo Apagando para refazer...
        rmdir /s /q ".venv"
    ) else (
        echo Ambiente .venv ja existe e funciona neste PC.
        goto :dependencias
    )
)

echo Criando o ambiente .venv ...
%PY% -m venv .venv
if errorlevel 1 (
    echo [ERRO] Nao consegui criar o ambiente.
    pause
    exit /b 1
)

:dependencias
echo.
echo Instalando as dependencias (pode demorar alguns minutos)...
echo.
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERRO] Falhou instalando as dependencias. Verifique a internet.
    pause
    exit /b 1
)

REM ---- conferir que funciona de verdade ---------------------------------
echo.
echo ==========================================================
echo   Conferindo...
echo ==========================================================
echo.
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 (
    echo.
    echo [ATENCAO] Algum teste falhou.
    echo.
    echo A prancha de referencia "SEM NADA.dxf" ja vem junto nesta pasta,
    echo entao o problema NAO e arquivo faltando: e alguma coisa no codigo.
    echo Anote a mensagem acima antes de fechar esta janela.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   PRONTO. Este PC esta preparado.
echo ==========================================================
echo.
echo Para abrir o programa:
echo    ABRIR PROGRAMA.bat
echo.
echo Para trabalhar no codigo com o Claude, abra o Claude Code
echo nesta pasta. O arquivo CLAUDE.md ja explica o projeto a ele.
echo.
pause
