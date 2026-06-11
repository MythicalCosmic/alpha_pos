"""Self-update for the packaged desktop app, built on tufup (The Update
Framework for Python).

Goal: fix a bug -> publish a new bundle to the cloud server -> every POS picks
it up on next launch. No reinstall, no rebuilding the installer, and updates are
cryptographically signed so a compromised server can't push arbitrary code.

Design constraints (why this module is defensive):
  * It runs at the very start of the desktop launcher, BEFORE the POS comes up.
    A bug here must never prevent the app from starting, so every path is
    wrapped and failures degrade to "run the current version".
  * It is a deliberate no-op unless ALL of these hold:
      - running as a frozen build (sys.frozen) — updates replace bundled files;
      - ALPHA_POS_UPDATE_URL is set (the base URL the server serves the tufup
        repo from, e.g. https://pos.<ip>.nip.io/updates);
      - tufup is importable;
      - a trusted root.json shipped with the build (so trust is bootstrapped
        from something we signed, not from the network).
    In dev (python -m desktop.app) it does nothing.

A small JSON state file (update_state.json, next to the downloaded metadata)
records the last check time, the last applied update + version history, and the
latest version the server advertised — surfaced on the panel's Updates page.

One-time setup, the release flow, hosting and rollback are documented in
desktop/UPDATES.md.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from desktop.version import APP_NAME, __version__

logger = logging.getLogger("desktop.updater")

# Env var the operator sets (desktop Configuration tab / config_store) to point
# at the server hosting the tufup repo. Unset => updates disabled.
UPDATE_URL_ENV = "ALPHA_POS_UPDATE_URL"

# A health marker: written just before we hand control to a freshly-applied
# version and cleared once that version has started cleanly. If we boot and find
# it still set, the previous update failed to come up — log loudly so the
# operator can roll back (see UPDATES.md). Kept simple on purpose.
_PENDING_MARKER = "update_pending.flag"
_STATE_FILE = "update_state.json"


def _data_dir() -> Path:
    base = Path(os.environ.get("ALPHA_POS_DATA_DIR") or os.environ.get("LOCALAPPDATA")
                or str(Path.home()))
    # ALPHA_POS_DATA_DIR is already .../AlphaPOS (set by config_store once Django
    # boots); LOCALAPPDATA is .../Local. Anchor on a single AlphaPOS dir either
    # way so the path is the same whether we're called early (launcher) or late
    # (the panel reads status) — never .../AlphaPOS/AlphaPOS/update.
    root = base if base.name.lower() == "alphapos" else base / "AlphaPOS"
    d = root / "update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_state() -> dict:
    try:
        return json.loads((_data_dir() / _STATE_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt => start fresh
        return {}


def _save_state(state: dict) -> None:
    try:
        (_data_dir() / _STATE_FILE).write_text(
            json.dumps(state, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — state is best-effort, never fatal
        logger.debug("could not persist update state", exc_info=True)


def _bundled_root() -> Path | None:
    """The trusted root.json shipped inside the frozen build (PyInstaller puts
    bundled data next to the executable / in sys._MEIPASS)."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "tuf_root" / "root.json")
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "tuf_root" / "root.json")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _enabled() -> tuple[bool, str]:
    if not getattr(sys, "frozen", False):
        return False, "not a frozen build (dev run)"
    if not os.environ.get(UPDATE_URL_ENV):
        return False, f"{UPDATE_URL_ENV} not set"
    try:
        import tufup.client  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"tufup not available: {e}"
    if _bundled_root() is None:
        return False, "no bundled trusted root.json"
    return True, "ok"


def _make_client():
    """Build a tufup Client against the configured update server. Caller must
    have confirmed _enabled() first. Bootstraps trust from the bundled root on
    first run."""
    from tufup.client import Client

    base_url = os.environ[UPDATE_URL_ENV].rstrip("/")
    data = _data_dir()
    metadata_dir = data / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Bootstrap trust: copy the bundled root.json into the metadata dir on first
    # run so tufup has a signed starting point it can update from.
    root_dst = metadata_dir / "root.json"
    if not root_dst.exists():
        shutil.copy2(_bundled_root(), root_dst)

    targets_dir = data / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)

    # The install dir is where the frozen onedir build lives (parent of the exe).
    install_dir = Path(sys.executable).resolve().parent

    return Client(
        app_name=APP_NAME,
        app_install_dir=install_dir,
        current_version=__version__,
        metadata_dir=metadata_dir,
        metadata_base_url=f"{base_url}/metadata/",
        target_dir=targets_dir,
        target_base_url=f"{base_url}/targets/",
        refresh_required=False,
    )


def _clear_pending():
    try:
        (_data_dir() / _PENDING_MARKER).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def mark_started_ok():
    """Call once the app has started cleanly so a previous update is confirmed
    healthy. Safe to call always; no-op when nothing is pending. When a pending
    marker is found it records the just-applied version + time into the update
    history before clearing it."""
    marker = _data_dir() / _PENDING_MARKER
    if marker.exists():
        try:
            applied = marker.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            applied = ""
        st = _load_state()
        st["last_update_at"] = _now_iso()
        if applied:
            st["last_update_version"] = applied
            history = st.get("history") or []
            history.append({"version": applied, "at": st["last_update_at"]})
            st["history"] = history[-20:]  # keep the last 20 updates
        # We're now running this version, so nothing newer is pending.
        st["last_available"] = None
        _save_state(st)
        logger.info("update applied and started cleanly; clearing pending marker")
    _clear_pending()


def get_status_info() -> dict:
    """Everything the panel's Updates page needs: current version, whether
    updates are enabled (and why not), the configured server, pending state, and
    the recorded last-check / last-update / available-version / history."""
    enabled, why = _enabled()
    st = _load_state()
    return {
        "version": __version__,
        "app_name": APP_NAME,
        "enabled": enabled,
        "reason": why,
        "frozen": bool(getattr(sys, "frozen", False)),
        "update_url": os.environ.get(UPDATE_URL_ENV, ""),
        "pending": (_data_dir() / _PENDING_MARKER).exists(),
        "last_check_at": st.get("last_check_at"),
        "last_check_ok": st.get("last_check_ok"),
        "last_check_error": st.get("last_check_error"),
        "last_update_at": st.get("last_update_at"),
        "last_update_version": st.get("last_update_version"),
        "available": st.get("last_available"),
        "history": st.get("history") or [],
    }


def check_only() -> dict:
    """Check the update server WITHOUT applying anything. Returns
    {current, available, enabled, error}; records the check time + the version
    the server advertised so the Updates page can show 'up to date' or offer an
    install. Never restarts. Never raises."""
    current = __version__
    st = _load_state()
    st["last_check_at"] = _now_iso()
    enabled, why = _enabled()
    if not enabled:
        st["last_check_ok"] = False
        st["last_check_error"] = why
        st["last_available"] = None
        _save_state(st)
        return {"current": current, "available": None, "enabled": False, "reason": why}
    try:
        new_update = _make_client().check_for_updates()
        available = str(new_update.version) if new_update else None
        st["last_check_ok"] = True
        st["last_check_error"] = ""
        st["last_available"] = available
        _save_state(st)
        return {"current": current, "available": available, "enabled": True}
    except Exception as e:  # noqa: BLE001 — checks must never crash the panel
        logger.exception("update check failed")
        st["last_check_ok"] = False
        st["last_check_error"] = str(e)
        _save_state(st)
        return {"current": current, "available": None, "enabled": True, "error": str(e)}


def check_and_apply() -> bool:
    """Check the update server and, if a newer signed bundle exists, download and
    apply it. On apply, tufup replaces the install and the process restarts, so
    this call does not return normally in that case.

    Returns False when nothing was done (disabled, up to date, or any error —
    all non-fatal). Never raises.
    """
    enabled, why = _enabled()
    st = _load_state()
    st["last_check_at"] = _now_iso()
    if not enabled:
        st["last_check_ok"] = False
        st["last_check_error"] = why
        _save_state(st)
        logger.debug("self-update skipped: %s", why)
        return False

    # A still-present marker means the last applied update never confirmed a
    # clean start. Surface it; don't block (the operator can roll back per docs).
    if (_data_dir() / _PENDING_MARKER).exists():
        logger.error(
            "previous update did not confirm a clean start — if the app is "
            "misbehaving, roll back per desktop/UPDATES.md"
        )

    try:
        client = _make_client()
        new_update = client.check_for_updates()
        if not new_update:
            st["last_check_ok"] = True
            st["last_check_error"] = ""
            st["last_available"] = None
            _save_state(st)
            logger.info("self-update: already on the latest version (%s)", __version__)
            return False

        st["last_check_ok"] = True
        st["last_available"] = str(new_update.version)
        _save_state(st)
        logger.warning("self-update: applying new version -> %s", new_update.version)
        # Mark pending BEFORE applying; mark_started_ok() clears it (and records
        # history) once the new version boots cleanly.
        try:
            (_data_dir() / _PENDING_MARKER).write_text(str(new_update.version))
        except Exception:  # noqa: BLE001
            pass

        # tufup extracts the new bundle and restarts the app (on Windows via a
        # batch helper). Control normally does not return past this call.
        client.download_and_apply_update(skip_confirmation=True)
        return True
    except Exception as e:  # noqa: BLE001 — updates must never crash the launcher
        st["last_check_ok"] = False
        st["last_check_error"] = str(e)
        _save_state(st)
        logger.exception("self-update failed; continuing on the current version")
        return False
