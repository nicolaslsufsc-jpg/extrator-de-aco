@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================================
echo   ENVIAR O PROJETO PARA O GITHUB
echo ==========================================================
echo.
echo   github.com/nicolaslsufsc-jpg/extrator-de-aco
echo.
echo Na PRIMEIRA vez vai abrir uma janela pedindo login do
echo GitHub. Escolha "Sign in with your browser" e autorize.
echo Depois disso ele nunca mais pergunta.
echo.

git add -A
git diff --cached --quiet
if errorlevel 1 (
    echo Gravando as alteracoes...
    git commit -m "Atualizacao do Extrator de Aco"
) else (
    echo Nada novo para gravar.
)

echo.
echo Enviando...
echo.
git push -u origin main

if errorlevel 1 (
    echo.
    echo ==========================================================
    echo   NAO DEU CERTO
    echo ==========================================================
    echo.
    echo Se falou em autenticacao, rode de novo e faca o login
    echo na janela que abrir.
    echo.
) else (
    echo.
    echo ==========================================================
    echo   PRONTO - projeto no GitHub
    echo ==========================================================
    echo.
    echo   https://github.com/nicolaslsufsc-jpg/extrator-de-aco
    echo.
    echo Deste dia em diante, e so rodar este arquivo de novo
    echo sempre que quiser salvar o trabalho na nuvem.
    echo.
)
pause
