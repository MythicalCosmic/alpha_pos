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

One-time setup, the release flow, hosting and rollback are documented in
desktop/UPDATES.md.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
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


def _data_dir() -> Path:
    base = os.environ.get("ALPHA_POS_DATA_DIR") or os.environ.get("LOCALAPPDATA") \
        or str(Path.home())
    d = Path(base) / "AlphaPOS" / "update"
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def _clear_pending():
    try:
        (_data_dir() / _PENDING_MARKER).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def mark_started_ok():
    """Call once the app has started cleanly so a previous update is confirmed
    healthy. Safe to call always; no-op when nothing is pending."""
    marker = _data_dir() / _PENDING_MARKER
    if marker.exists():
        logger.info("update applied and started cleanly; clearing pending marker")
    _clear_pending()


def check_and_apply() -> bool:
    """Check the update server and, if a newer signed bundle exists, download and
    apply it. On apply, tufup replaces the install and the process restarts, so
    this call does not return normally in that case.

    Returns False when nothing was done (disabled, up to date, or any error —
    all non-fatal). Never raises.
    """
    enabled, why = _enabled()
    if not enabled:
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
        from tufup.client import Client

        base_url = os.environ[UPDATE_URL_ENV].rstrip("/")
        data = _data_dir()
        metadata_dir = data / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        # Bootstrap trust: copy the bundled root.json into the metadata dir on
        # first run so tufup has a signed starting point it can update from.
        root_dst = metadata_dir / "root.json"
        if not root_dst.exists():
            shutil.copy2(_bundled_root(), root_dst)

        targets_dir = data / "targets"
        targets_dir.mkdir(parents=True, exist_ok=True)

        # The install dir is where the frozen onedir build lives (parent of the
        # exe). tufup swaps this directory's contents on update.
        install_dir = Path(sys.executable).resolve().parent

        client = Client(
            app_name=APP_NAME,
            app_install_dir=install_dir,
            current_version=__version__,
            metadata_dir=metadata_dir,
            metadata_base_url=f"{base_url}/metadata/",
            target_dir=targets_dir,
            target_base_url=f"{base_url}/targets/",
            refresh_required=False,
        )

        new_update = client.check_for_updates()
        if not new_update:
            logger.info("self-update: already on the latest version (%s)", __version__)
            return False

        logger.warning("self-update: applying new version -> %s", new_update.version)
        # Mark pending BEFORE applying; mark_started_ok() clears it once the new
        # version boots cleanly.
        try:
            (_data_dir() / _PENDING_MARKER).write_text(str(new_update.version))
        except Exception:  # noqa: BLE001
            pass

        # tufup extracts the new bundle and restarts the app (on Windows via a
        # batch helper). Control normally does not return past this call.
        client.download_and_apply_update(skip_confirmation=True)
        return True
    except Exception:  # noqa: BLE001 — updates must never crash the launcher
        logger.exception("self-update failed; continuing on the current version")
        return False
