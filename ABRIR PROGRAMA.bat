@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ==========================================================
echo   EXTRATOR DE ACO
echo ==========================================================
echo.

REM ---- o ambiente deste PC precisa existir ----------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Este computador ainda nao foi preparado.
    echo.
    echo Rode primeiro:  INSTALAR NO PC NOVO.bat
    echo.
    pause
    exit /b 1
)

echo Abrindo a tela do programa no navegador...
echo.
echo   Endereco:  http://127.0.0.1:8501
echo.
echo Deixe ESTA JANELA PRETA ABERTA enquanto usa o programa.
echo Ela e o motor: se fechar, a tela para de funcionar.
echo.
echo Para encerrar, feche esta janela ou aperte Ctrl+C.
echo.

REM Espera o servidor subir antes de chamar o navegador, senao a
REM primeira tentativa cai numa pagina de erro e assusta.
start "" /b cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8501"

.venv\Scripts\python.exe -m streamlit run streamlit_app.py ^
    --server.address=127.0.0.1 ^
    --server.port=8501 ^
    --server.headless=true

echo.
echo Programa encerrado.
pause
