@echo off
REM Launcher robusto para usuario nao-tecnico.
REM Detecta o Python, instala dependencias no primeiro uso e roda a validacao.
REM Comentarios em ASCII de proposito: acento em REM confunde o cmd.
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Validador de Pedidos - GoCase
echo ============================================
echo.

REM --- 1. Detecta um Python que realmente funcione ---
REM Tenta 'python'; se falhar, tenta o launcher 'py'. Verifica de fato que
REM o comando executa (o stub da Microsoft Store responde 'python' mas nao roda).
set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY (
  py --version >nul 2>nul && set "PY=py"
)

if not defined PY (
  echo [ERRO] Python nao encontrado neste computador.
  echo.
  echo   Instale o Python 3.10 ou superior:
  echo   https://www.python.org/downloads/
  echo.
  echo   IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
  echo.
  pause
  exit /b 1
)

REM --- 2. Instala dependencias no primeiro uso ---
REM O marcador .deps_ok evita reinstalar a cada execucao.
if not exist ".deps_ok" (
  echo Primeira execucao: instalando dependencias...
  echo.
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar as dependencias.
    echo   Verifique sua conexao com a internet e tente de novo.
    echo.
    pause
    exit /b 1
  )
  echo ok> ".deps_ok"
  echo.
  echo Dependencias instaladas.
  echo.
)

REM --- 3. Executa a validacao ---
echo Processando planilha de pedidos...
echo.
%PY% main.py
if errorlevel 1 (
  echo.
  echo [ERRO] A validacao terminou com erro. Veja as mensagens acima
  echo   ou o log em output\_sistema\log_execucao.log
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Concluido. Resultados na pasta "output":
echo     - pedidos_validados.xlsx
echo     - pedidos_rejeitados.xlsx
echo     - resumo_execucao.xlsx
echo ============================================
echo.
pause
