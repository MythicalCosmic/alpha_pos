@echo off
REM ============================================================
REM  Alpha POS - Windows installer (double-click this file)
REM ============================================================
REM
REM  Run this ONCE on a fresh PC. It will:
REM    1. Check Python 3.11+ is on PATH
REM    2. Create a private virtualenv in .\.venv
REM    3. Install all Python dependencies
REM    4. Initialize the database + create the first admin
REM
REM  After this finishes, double-click start.bat to launch the
REM  POS every time you turn the PC on.
REM
REM  If anything in here fails, the install will stop and show
REM  you the error. Don't proceed to start.bat until install.bat
REM  completes with "Install complete".
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo Alpha POS installer
echo ===================
echo.

REM --- Step 1: Python available? -------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python is not installed or not on PATH.
    echo.
    echo     Install Python 3.11 or newer from https://www.python.org/downloads/
    echo     IMPORTANT: tick "Add Python to PATH" on the installer's first page.
    echo.
    pause
    exit /b 1
)

REM --- Step 2: Create virtualenv -------------------------------
if not exist ".venv" (
    echo [1/3] Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [X] Failed to create virtualenv.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtualenv already exists, reusing.
)

REM --- Step 3: Install dependencies ----------------------------
echo [2/3] Installing dependencies (this takes a minute) ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Failed to install dependencies.
    pause
    exit /b 1
)

REM --- Step 4: Initialize DB + create admin --------------------
echo [3/3] Initializing database and creating admin user ...

REM Generate a SECRET_KEY into .secret_key if missing so this and
REM all later runs share the same key (sessions / encrypted state
REM survive across reinstalls of the same project tree).
if not exist ".secret_key" (
    python -c "import secrets; open('.secret_key','w').write(secrets.token_urlsafe(64) + '\n')"
)

REM Read SECRET_KEY into the environment for this process so the
REM migrate + bootstrap_admin steps below don't fall back to a
REM "not configured" error in non-DEBUG mode.
for /f "usebackq delims=" %%K in (".secret_key") do set SECRET_KEY=%%K
set DEBUG=False
set ALLOWED_HOSTS=localhost,127.0.0.1

python manage.py migrate --noinput
if errorlevel 1 (
    echo [X] Database migration failed.
    pause
    exit /b 1
)
python manage.py bootstrap_admin
if errorlevel 1 (
    echo [X] Admin bootstrap failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Install complete.
echo.
echo  Write down the admin email + password printed above.
echo  You will need them to log in the first time.
echo.
echo  Double-click start.bat to launch Alpha POS.
echo ============================================================
echo.
pause
endlocal
