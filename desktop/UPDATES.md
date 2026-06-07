# Desktop self-update (tufup)

Goal: **fix a bug → publish → every POS updates itself on next launch.** No
reinstalling, no rebuilding the installer each time, and updates are
cryptographically signed so a compromised server can't push arbitrary code.

Pieces:

| Piece | File | Role |
|-------|------|------|
| Version | `desktop/version.py` | single source of truth; bump per release |
| Client | `desktop/updater.py` | checks + applies updates at launch (fail-safe) |
| Publisher | `tools/release.py` | builds & signs a bundle, updates the repo |
| Wiring | `desktop/app.py` `main()` | calls `updater.check_and_apply()` first |

The client is a **guaranteed no-op** unless it's a frozen build, `tufup` is
installed, `ALPHA_POS_UPDATE_URL` is set, and a trusted `tuf_root/root.json` is
bundled. Any failure falls back to "run the current version" — updating can
never brick the app. `--no-update` skips the check.

---

## One-time setup

### 1. Create signing keys + the repo (on your build machine, ONCE)

```bash
pip install -r requirements-desktop.txt
python tools/release.py --init
```

This creates:
- `update_keys/` — **PRIVATE signing keys. Back these up offline; never commit
  or upload them.** (Already gitignored.) Losing the root key means clients
  can't trust a new key set without a reinstall.
- `update_repo/` — the metadata + targets you publish to the server.

### 2. Bundle the trusted root into the installer

Clients bootstrap trust from a `root.json` shipped *inside* the build (not the
network). Add it to `AlphaPOS.spec` `datas` so PyInstaller bundles it as
`tuf_root/root.json`:

```python
# AlphaPOS.spec
datas += [('update_repo/metadata/root.json', 'tuf_root')]
```

`updater._bundled_root()` looks for it in `sys._MEIPASS/tuf_root/root.json` and
next to the exe.

### 3. Point the app at the update server

Set on each POS (desktop Configuration tab / env), e.g.:

```
ALPHA_POS_UPDATE_URL = https://pos.<server-ip>.nip.io/updates
```

The server must serve `update_repo/` at that URL, i.e.
`…/updates/metadata/…` and `…/updates/targets/…`. With the existing Caddy
setup, add a static file server (or an Nginx/`alias`) for the repo directory.

---

## Each release

```bash
# 1. Bump the version
#    desktop/version.py  ->  __version__ = "1.0.1"

# 2. Build the onedir PyInstaller bundle (must be onedir, not onefile, so tufup
#    can swap files):
pyinstaller AlphaPOS.spec        # produces dist/AlphaPOS/

# 3. Sign + add it to the repo
python tools/release.py --publish --bundle dist/AlphaPOS

# 4. Push the repo to the server path behind ALPHA_POS_UPDATE_URL
rsync -a update_repo/ <server>:/srv/alpha_pos/updates/
```

Next time each POS launches it sees the new signed version, downloads the delta,
verifies signatures, applies it and restarts. No operator action on the tills.

---

## Health check & rollback

`updater.py` writes `update_pending.flag` just before applying and clears it once
the new version starts cleanly (`mark_started_ok()`). If a launch finds the flag
still set, the previous update didn't confirm a clean start and it logs an error.

To roll back, publish the previous version again (bump `version.py` to a higher
number containing the old code, or re-`--publish` the prior bundle). tufup also
retains downloaded archives under the per-user update dir
(`%LOCALAPPDATA%/AlphaPOS/update/`) for manual recovery.

---

## Notes / caveats

- Built and wired but **not yet validated end-to-end** (needs a Windows build +
  a hosted repo). Treat the first release as a dry run: publish to a staging URL
  and point one POS at it before rolling out.
- tufup's `Repository` / `Client` API shifts between versions. This targets
  `tufup ~0.9`; if you bump the pin, re-check the calls in `updater.py` and
  `tools/release.py`.
- Updates require the **onedir** PyInstaller layout (file-swap). A onefile
  `.exe` can't be updated in place — keep `AlphaPOS.spec` (onedir) for releases
  that use auto-update; `AlphaPOS-onefile.spec` is for standalone distribution
  without updates.
