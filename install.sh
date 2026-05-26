#!/usr/bin/env bash
# ============================================================
#  Alpha POS - Linux/Mac installer
# ============================================================
#
#  Run this ONCE on a fresh machine:
#      bash install.sh
#
#  Equivalent to install.bat on Windows.
# ============================================================
set -eu

cd "$(dirname "$0")"

echo
echo "Alpha POS installer"
echo "==================="
echo

# --- Step 1: Python --------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[X] python3 not found. Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

# --- Step 2: Virtualenv ---------------------------------------------
if [ ! -d ".venv" ]; then
    echo "[1/3] Creating virtual environment in .venv ..."
    python3 -m venv .venv
else
    echo "[1/3] Virtualenv already exists, reusing."
fi

# shellcheck disable=SC1091
. .venv/bin/activate

# --- Step 3: Dependencies -------------------------------------------
echo "[2/3] Installing dependencies (this takes a minute) ..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

# --- Step 4: SECRET_KEY + migrate + bootstrap admin ------------------
echo "[3/3] Initializing database and creating admin user ..."

if [ ! -f ".secret_key" ]; then
    python -c "import secrets; open('.secret_key','w').write(secrets.token_urlsafe(64) + '\n')"
    chmod 600 .secret_key
fi

# Read SECRET_KEY into env for the rest of this script so settings.py
# doesn't raise in non-DEBUG mode.
export SECRET_KEY
SECRET_KEY="$(cat .secret_key)"
export DEBUG=False
export ALLOWED_HOSTS=localhost,127.0.0.1

python manage.py migrate --noinput
python manage.py bootstrap_admin

echo
echo "============================================================"
echo "  Install complete."
echo
echo "  Write down the admin email + password printed above."
echo "  You will need them to log in the first time."
echo
echo "  Run:   bash start.sh"
echo "  to launch Alpha POS."
echo "============================================================"
