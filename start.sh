#!/usr/bin/env bash
# ============================================================
#  Alpha POS - daily launcher
# ============================================================
set -eu
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
    echo "[X] Virtualenv missing. Run 'bash install.sh' first."
    exit 1
fi

# shellcheck disable=SC1091
. .venv/bin/activate

echo "Starting Alpha POS on http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."
echo

exec python run.py
