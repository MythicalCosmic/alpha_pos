#!/usr/bin/env python
"""One-command launcher for restaurants installing on a single PC.

The operator double-clicks `start.bat` (Windows) or runs `python run.py`
(any OS) and the system:
  1. Generates a SECRET_KEY into `.secret_key` if missing — so the first
     boot doesn't crash on the "SECRET_KEY required" check.
  2. Applies database migrations.
  3. Creates a first ADMIN user if none exist, prints the credentials.
  4. Starts the Django dev server on http://127.0.0.1:8000 (or PORT env).

This is NOT the production entry. Production deployments use gunicorn
via `entrypoint.sh` (or `waitress-serve` on Windows servers) — see
README. `run.py` is for a single restaurant PC where one cashier app
talks to one local Django process.

Idempotent: re-running does not duplicate the admin or rotate the key.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_FILE = BASE_DIR / '.secret_key'


def _load_or_generate_secret() -> str:
    """Read .secret_key, or generate + write one on first run.

    Stored in BASE_DIR so a reinstall against the same project tree
    keeps the same key (session cookies / encrypted payloads survive).
    Gitignored — never committed.
    """
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding='utf-8').strip()

    new_key = secrets.token_urlsafe(64)
    SECRET_FILE.write_text(new_key + '\n', encoding='utf-8')
    # POSIX: 0600 so other users on the box can't read it. On Windows
    # this is a no-op (chmod is not enforced), but the .gitignore entry
    # is the primary protection.
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return new_key


def _ensure_env_defaults() -> None:
    """Populate the env vars settings.py reads, without overwriting any
    that the operator already set. Order matters: SECRET_KEY first
    because the settings module raises at import if it's missing in
    non-DEBUG mode."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')
    os.environ.setdefault('SECRET_KEY', _load_or_generate_secret())
    # Default to a real production-ish mode (DEBUG=False, ALLOWED_HOSTS
    # explicit) so a fresh install behaves the same on day-1 as it will
    # in production. The operator can flip DEBUG=true in a .env if they
    # want the dev experience.
    os.environ.setdefault('DEBUG', 'False')
    os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1')


def _run_management(*argv: str) -> None:
    """Invoke a Django management command in-process. Exits the script
    if the command returns non-zero, so a migrate failure doesn't leave
    a half-installed system happily serving requests."""
    from django.core.management import execute_from_command_line
    try:
        execute_from_command_line(['run.py', *argv])
    except SystemExit as exc:
        if exc.code not in (0, None):
            sys.stderr.write(f'run.py: `{argv[0]}` exited with code {exc.code}\n')
            raise


def main() -> None:
    _ensure_env_defaults()

    import django
    django.setup()

    print('[1/3] Applying database migrations...')
    _run_management('migrate', '--noinput')

    print('[2/3] Bootstrapping admin (idempotent)...')
    _run_management('bootstrap_admin')

    host = os.environ.get('HOST', '127.0.0.1')
    port = os.environ.get('PORT', '8000')
    print(f'[3/3] Starting server on http://{host}:{port}  (Ctrl+C to stop)')
    # `runserver` is fine for single-PC use. For multi-cashier deployments
    # the operator should run this app behind `waitress-serve` (Windows)
    # or `gunicorn` (Linux/Docker) — see README.
    _run_management('runserver', f'{host}:{port}', '--noreload')


if __name__ == '__main__':
    main()
