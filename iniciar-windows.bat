@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title API-SUS

rem Abre o API-SUS a partir do codigo (para quem tem Python 3.10 ou mais novo).
rem Na primeira vez cria o ambiente .venv e instala as dependencias (precisa de internet).

if exist ".venv\Scripts\python.exe" goto dependencias

set "PYTHON="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
  echo ERRO: Python 3.10 ou mais novo não foi encontrado.
  echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH",
  echo ou use o executável API-SUS-windows.exe da release "app".
  goto erro
)

echo Primeira execução: criando o ambiente Python em .venv ...
%PYTHON% -m venv .venv
if errorlevel 1 (
  echo ERRO: não foi possível criar o ambiente Python em .venv.
  goto erro
)

:dependencias
echo Conferindo as dependências (na primeira vez demora alguns minutos)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo ERRO: não foi possível instalar as dependências. Verifique a internet e tente de novo.
  goto erro
)

".venv\Scripts\python.exe" -m app.desktop
if errorlevel 1 goto erro
exit /b 0

:erro
echo.
pause
exit /b 1
