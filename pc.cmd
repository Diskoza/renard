@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" call "%ROOT%setup.cmd" || exit /b 1
chcp 65001 >nul
cd /d "%ROOT%"
"%ROOT%.venv\Scripts\python.exe" -m agent.tui %*
