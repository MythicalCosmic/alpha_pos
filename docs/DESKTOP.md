# Alpha POS desktop control panel

A native (pywebview) GUI for the single restaurant PC. It bootstraps the install
on first run, lets the operator enter the business's config, starts/stops the
local POS server, and runs the built-in self-tests.

## What it does

- **First run:** accept the Terms of Service, then the first time you press
  **Start** it auto-installs everything (DB migrations → admin account →
  static files).
- **Big Start/Stop button:** runs the Django POS server in-process via
  `waitress` on `http://127.0.0.1:8000`.
- **Dashboards:** sync heartbeat, subscription/license, account balance,
  fiscalization status.
- **Configuration tab:** branch, license control-center URL, cloud sync,
  Telegram, and the **fiscal identity (this business's TIN + provider creds)** —
  saved to `.env`.
- **Tests tab:** test server connection · send/get mock sync data · Telegram bot
  test · fake notification · fiscalization test (mock sign + QR).
- **Fiscalization tab:** flip mode off/mock/sandbox/live live; run a test.
- **License & Subscription tab:** view status/expiry/balance, register online
  against the control center + pick a plan, request a plan change, run a
  heartbeat, or **activate offline** (interim, no control center needed).
- **Notifications tab:** admin Telegram **bot token + chat IDs** (real delivery,
  saved to NotificationSettings), brand name, and a **message-layout editor** —
  edit each notification template's text with live preview + safe-placeholder
  validation, wired to the real notification models.
- **Open full admin panel:** opens Django admin (`/admin/`) — full CRUD over
  every backend model (products, users, stock, loyalty, queue, …). Telegram
  message delivery is REAL (calls api.telegram.org); it needs a bot token + chat
  IDs to actually send. The inbound ordering bot additionally needs the webhook
  pointed at a public HTTPS URL Telegram can reach (not localhost).

## Run from source (dev)

```
.venv/Scripts/python.exe -m pip install -r requirements-desktop.txt
.venv/Scripts/python.exe -m desktop.app
```
Headless smoke test (no GUI): `.venv/Scripts/python.exe -m desktop._smoketest`

## Build the .exe + installer (on Windows)

```
.venv/Scripts/pyinstaller AlphaPOS.spec          # -> dist/AlphaPOS/AlphaPOS.exe
iscc installer/AlphaPOS.iss                       # -> Output/AlphaPOS-Setup.exe
```
`AlphaPOS-Setup.exe` is the single file you give a customer: it installs the app,
they accept the ToS in the GUI, and the first Start sets everything up.

Notes:
- The GUI uses Edge **WebView2**, pre-installed on Windows 11 (bundle the
  Evergreen runtime in the installer for older Windows 10 if needed).
- Single-PC mode uses **SQLite** (no Postgres/Redis to install) — the WAL +
  busy-timeout config in `settings.py` handles concurrent till access.
- Config lives in `.env`; secrets (`.secret_key`, `.license_fernet_key`) are
  generated once and persist across upgrades. All are gitignored.
- Changing credentials needs a server **restart** (the GUI says so); the fiscal
  **mode** toggle applies live.
