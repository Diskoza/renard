@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating venv...
  py -3.11 -m venv .venv || goto :err
  .venv\Scripts\python -m pip install -q -r requirements.txt || goto :err
)
start "" http://127.0.0.1:8790
.venv\Scripts\python -m agent
goto :eof
:err
echo Setup failed.
pause
