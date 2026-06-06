# Alpha POS — Desktop Installer

One file to give the client: **`installer\Output\AlphaPOS-Setup.exe`**.

All Python (Django, the POS apps, the runtime) is compiled into the bundle — no
readable source ends up on the client PC. The client never sees the internal
files; the installer unpacks everything itself.

## Build it (developer machine)

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

That runs the three steps: icon → PyInstaller bundle (`dist\AlphaPOS\`) → Inno
Setup (`installer\Output\AlphaPOS-Setup.exe`). Requires the project `.venv` and
Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

To rebuild only the app bundle: `.venv\Scripts\pyinstaller --clean AlphaPOS.spec`.

## What the client experiences

1. Double-clicks `AlphaPOS-Setup.exe`.
2. **Accepts the Terms of Service** (license page).
3. **Chooses the install folder** (or accepts the default in Program Files).
4. Installs; gets a desktop + Start-menu shortcut.
5. Opens **Alpha POS** — a control panel in a clean app window (Edge app mode).
6. Accepts the in-app Terms, then presses the big **Start Server** button. The
   first Start automatically: applies the database migrations, creates the admin
   account, and collects static files ("installs everything").
7. The **Dashboard** shows the admin **email + password** for signing in to the
   POS / admin panel (with a copy button) — this is generated on first Start and
   stored on this PC.

## Where data lives

Per-user, persistent, survives upgrades and uninstall-without-data:

```
%LOCALAPPDATA%\AlphaPOS\
  db.sqlite3              the database
  .env                    this business's settings + fiscal identity
  .secret_key             generated Django secret (strong, per install)
  .license_fernet_key     generated license-encryption key
  admin_credentials.json  the first-admin login shown in the panel
  staticfiles\  logs\  private_media\
```

Uninstalling offers to delete this folder (default: **keep**, for reinstalls).

## Fiscalization (v1)

Shipped **OFF / fully bypassed** — no receipts, no Soliq calls. Switch it on
later from the Fiscalization tab (mock / sandbox / live) once a business enters
its own TIN + provider credentials.

## Security notes (addressed)

- Each install generates its own strong `SECRET_KEY` and license key.
- The control panel's localhost API requires a per-launch token and validates
  the Host header (no other page in the browser can drive it).
- Production runs `DEBUG=False`; CORS is locked to an explicit allowlist.
