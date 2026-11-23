@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\pythonw.exe" call "%ROOT%setup.cmd" || exit /b 1
cd /d "%ROOT%"
start "" "%ROOT%.venv\Scripts\pythonw.exe" -m agent.desktop
