"""Local config + secret management for the desktop app.

Everything the operator enters lives in BASE_DIR/.env (the same env vars
settings.py reads). Secrets (SECRET_KEY, license Fernet key) are generated once
and persisted next to the project, mirroring run.py so a desktop launch and a
`python run.py` launch share state. Desktop-only flags (ToS acceptance) live in
config.json.

NOTE: .env holds this ONE business's own fiscal credentials. It is never shared
between installs.
"""
from __future__ import annotations

import json
import os
import secrets
import string
import sys
from pathlib import Path


def _data_dir() -> Path:
    """Persistent, writable data dir. In a packaged build BASE_DIR is a temp
    extraction dir wiped each launch, so we store DB/secrets/config under
    %LOCALAPPDATA%\\AlphaPOS instead. From source, use the project root."""
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA') or str(Path.home())
        return Path(base) / 'AlphaPOS'
    return Path(__file__).resolve().parent.parent


DATA_DIR = _data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = DATA_DIR / '.env'
SECRET_FILE = DATA_DIR / '.secret_key'
FERNET_FILE = DATA_DIR / '.license_fernet_key'
STATE_FILE = DATA_DIR / 'desktop_state.json'
CREDS_FILE = DATA_DIR / 'admin_credentials.json'
# Marker written by a factory reset so a leftover (locked) DB is wiped on the
# next launch, before Django opens it.
RESET_FLAG = DATA_DIR / '.reset_pending'

# The fields the control-panel config form manages, with sensible defaults.
# Grouped only for the UI; stored flat in .env.
CONFIG_FIELDS = [
    # General
    ('BRANCH_ID', 'branch1'),
    ('DEPLOYMENT_MODE', 'local'),
    ('PORT', '8000'),
    # Licensing / control center
    ('LICENSE_CONTROL_CENTER_URL', 'https://control.94.141.97.228.nip.io/'),
    # Self-update: base URL the server serves the signed tufup repo from
    # (…/updates/metadata/ + …/updates/targets/). Read by desktop/updater.py.
    # Blank disables updates. Baked to the production hub so a fresh install is
    # pre-wired once the repo is published + bundled root shipped.
    ('ALPHA_POS_UPDATE_URL', 'https://pos.94.141.97.228.nip.io/updates'),
    # Sync (cloud) — baked defaults point at the production hub so a fresh
    # install is pre-wired. CLOUD_SYNC_TOKEN is the per-branch token from the
    # server's .env (DESKTOP_BRANCH_TOKEN); fill it in the panel or bake it here.
    ('SYNC_ENABLED', 'True'),
    ('CLOUD_SYNC_URL', 'https://pos.94.141.97.228.nip.io/api/sync'),
    ('CLOUD_SYNC_TOKEN', 'yucTaCucvUTUknFa9EFvR0L0_BLkKStFW5Kyk1mDc8w'),
    # Telegram (token + chat ids drive real message delivery)
    ('TELEGRAM_BOT_TOKEN', '8809919796:AAF03pZ-IJpl-Ov4R74gs1ld7EYNtLs7T-k'),
    ('TELEGRAM_CHAT_IDS', '134385193,6589960007,493544586,1023732044'),
    ('TELEGRAM_WEBHOOK_SECRET', ''),
    # AI (stock assistant + demand forecast). Pick a provider, fill its key.
    ('AI_PROVIDER', 'claude'),  # 'claude' or 'gemini'
    ('ANTHROPIC_API_KEY', ''),
    ('ANTHROPIC_MODEL', 'claude-sonnet-4-6'),
    ('GEMINI_API_KEY', ''),
    ('GEMINI_MODEL', 'gemini-2.5-flash'),
    # Fiscalization (this business's OWN identity)
    ('FISCALIZATION_MODE', 'off'),
    ('FISCAL_PROVIDER', 'mock'),
    ('FISCAL_TIN', ''),
    ('FISCAL_PROVIDER_URL', ''),
    ('FISCAL_MERCHANT_ID', ''),
    ('FISCAL_SECRET', ''),
    ('FISCAL_VAT_PERCENT', '0'),
    ('FISCAL_BLOCK_ON_FAILURE', 'false'),
]

SECRET_KEYS = {'FISCAL_SECRET', 'CLOUD_SYNC_TOKEN', 'TELEGRAM_BOT_TOKEN',
               'TELEGRAM_WEBHOOK_SECRET', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY'}


def _write_protected(path: Path, contents: str) -> None:
    path.write_text(contents, encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_generate_secret() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding='utf-8').strip()
    key = secrets.token_urlsafe(64)
    _write_protected(SECRET_FILE, key + '\n')
    return key


def load_or_generate_fernet() -> str:
    if FERNET_FILE.exists():
        return FERNET_FILE.read_text(encoding='utf-8').strip()
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode('ascii')
    _write_protected(FERNET_FILE, key + '\n')
    return key


def parse_env_file() -> dict:
    data = {}
    if not ENV_FILE.exists():
        return data
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        data[k.strip()] = v.strip()
    return data


def read_config() -> dict:
    """Current config values for the form (existing .env merged over defaults)."""
    env = parse_env_file()
    return {k: env.get(k, default) for k, default in CONFIG_FIELDS}


def write_config(values: dict) -> None:
    """Persist the form values into .env, preserving any unmanaged keys."""
    existing = parse_env_file()
    for k, default in CONFIG_FIELDS:
        if k in values and values[k] is not None:
            existing[k] = str(values[k])
        else:
            existing.setdefault(k, default)
    lines = ['# Alpha POS configuration — generated by the desktop control panel',
             '# This file holds THIS business\'s own settings + fiscal identity.', '']
    for k in sorted(existing):
        lines.append(f'{k}={existing[k]}')
    _write_protected(ENV_FILE, '\n'.join(lines) + '\n')


def _wipe_data() -> list:
    """Delete ALL local data — DB, generated secrets, saved config/state, logs,
    static and media — so the next launch is a clean first install. Returns the
    paths actually removed. Best-effort: a file locked by a live DB connection
    is skipped here and finished by consume_reset_pending() on the next launch.
    """
    import shutil
    targets = [
        DATA_DIR / 'db.sqlite3', DATA_DIR / 'db.sqlite3-wal', DATA_DIR / 'db.sqlite3-shm',
        ENV_FILE, SECRET_FILE, FERNET_FILE, STATE_FILE, CREDS_FILE,
        DATA_DIR / 'logs', DATA_DIR / 'staticfiles', DATA_DIR / 'private_media',
    ]
    removed = []
    for p in targets:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                removed.append(str(p))
            elif p.exists():
                p.unlink()
                removed.append(str(p))
        except OSError:
            pass  # locked (live DB) — consume_reset_pending() retries next launch
    return removed


def factory_reset() -> dict:
    """Wipe everything now and arm a pending-reset marker so any file still
    locked by the running process is removed on the next launch."""
    removed = _wipe_data()
    try:
        RESET_FLAG.write_text('1', encoding='utf-8')
    except OSError:
        pass
    return {'removed': removed}


def consume_reset_pending() -> None:
    """If a reset was armed, finish it before Django touches the DB. Runs at the
    very start of apply_env_to_process so the wipe happens in a fresh process
    where nothing holds the sqlite file open."""
    try:
        if RESET_FLAG.exists():
            _wipe_data()
            RESET_FLAG.unlink(missing_ok=True)
    except OSError:
        pass


def apply_env_to_process() -> None:
    """Load .env + the generated secrets into os.environ. MUST run before
    django.setup() so settings.py sees them."""
    # Finish any armed factory reset first — before secrets are regenerated.
    consume_reset_pending()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')
    # Tell settings.py where to keep the DB / logs / media (persistent).
    os.environ.setdefault('ALPHA_POS_DATA_DIR', str(DATA_DIR))
    os.environ.setdefault('SECRET_KEY', load_or_generate_secret())
    os.environ.setdefault('LICENSE_FERNET_KEY', load_or_generate_fernet())
    os.environ.setdefault('DEBUG', 'False')
    os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1')
    # Trusted-LAN appliance: the POS is exposed to the whole network, so open
    # CSRF + CORS to any origin/device by default (auth + licensing still apply).
    os.environ.setdefault('OPEN_LAN', 'True')
    # Seed the baked-in config defaults so a FRESH install (no .env yet) runs
    # pre-configured — sync URL, Telegram, control-center URL — without the
    # operator having to open the panel. setdefault means real .env values
    # (loaded just below) always win.
    for _k, _default in CONFIG_FIELDS:
        if _default != '':
            os.environ.setdefault(_k, _default)
    for k, v in parse_env_file().items():
        os.environ[k] = v
    # The desktop binds the POS to the whole LAN (0.0.0.0), so devices reach it
    # by this machine's LAN IP / hostname. Allow any Host header — this is a
    # trusted-LAN appliance; auth + licensing are the real boundary, not Host
    # validation. (Ensures DHCP IP changes never lock the network out.)
    hosts = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
    if '*' not in hosts:
        hosts.append('*')
        os.environ['ALLOWED_HOSTS'] = ','.join(hosts)


def read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return {}
    return {}


def write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def generate_password(length: int = 14) -> str:
    """Readable random password (no ambiguous chars) for the bootstrap admin."""
    alphabet = string.ascii_letters + string.digits
    for bad in '0O1lI':
        alphabet = alphabet.replace(bad, '')
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def read_admin_creds() -> dict:
    """The first-admin login the desktop app created, so the panel can show it
    (the GUI exe has no console where the bootstrap banner would appear)."""
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return {}
    return {}


def write_admin_creds(email: str, password: str) -> None:
    _write_protected(CREDS_FILE, json.dumps({'email': email, 'password': password}, indent=2))


def tos_accepted() -> bool:
    return bool(read_state().get('tos_accepted'))


def accept_tos() -> None:
    state = read_state()
    state['tos_accepted'] = True
    write_state(state)
