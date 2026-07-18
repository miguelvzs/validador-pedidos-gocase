@echo off
REM Launcher for non-technical user: double-click runs the validator.
REM Must sit at project root so data/ and output/ paths resolve.
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Validador de Pedidos - GoCase
echo ============================================
echo.
echo Processando planilha de pedidos...
echo.

python main.py

echo.
echo ============================================
echo   Concluido. Resultados na pasta "output":
echo     - pedidos_validados.xlsx
echo     - pedidos_rejeitados.xlsx
echo     - resumo_execucao.xlsx
echo ============================================
echo.
pause
