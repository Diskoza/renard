@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating venv...
  py -3.11 -m venv .venv || exit /b 1
)
.venv\Scripts\python -m pip install -q -r requirements.txt || exit /b 1
echo Setup OK.
