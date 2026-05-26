@echo off
REM ============================================================
REM  Alpha POS - daily launcher (double-click this file)
REM ============================================================
REM
REM  Activates the virtualenv and runs the server on
REM  http://127.0.0.1:8000
REM
REM  Run install.bat ONCE before the first use of this script.
REM ============================================================

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [X] Virtualenv missing. Run install.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo Starting Alpha POS on http://127.0.0.1:8000
echo Close this window to stop the server.
echo.
python run.py

REM If run.py exits because of an error, pause so the operator can
REM read the message before the window closes.
if errorlevel 1 pause
endlocal
