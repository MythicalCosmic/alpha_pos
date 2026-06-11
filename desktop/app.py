"""Entry point for the Alpha POS desktop control panel.

    python -m desktop.app          # dev
    (or the packaged AlphaPOS.exe)

Starts the local control server, then shows the panel in a NATIVE window via
pywebview (WebView2 — an embedded rendering control, NOT the Edge browser: no
msedge.exe, no browser chrome). If the native window can't start, it falls back
to a chromeless Edge "--app" window, then the default browser, so the panel
always appears. Closing the window stops the POS server and exits.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from desktop import control_server

logger = logging.getLogger('desktop.app')


def _find_edge() -> str | None:
    candidates = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _profile_dir() -> str:
    base = os.environ.get('LOCALAPPDATA') or str(Path.home())
    p = Path(base) / 'AlphaPOS' / 'edge-profile'
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _selftest():
    """Validate a frozen build loads all modules + the pipeline works, without a
    display. Run: AlphaPOS.exe --selftest"""
    import json
    from desktop.bridge import Api
    api = Api()
    print('get_state :', json.dumps(api.get_state())[:80])
    api.run_setup()
    print('start     :', api.start_server().get('running'))
    print('conn      :', api.test_server_connection().get('status'))
    api.fiscal_set_mode('mock')
    print('mock sync :', api.send_mock_sync().get('read_back'))
    print('fiscal    :', api.fiscal_test().get('fiscal_sign'))
    api.stop_server()
    try:
        import webview  # noqa: F401 — confirms the native-GUI backend bundled
        print('webview   : importable (native window available)')
    except Exception as exc:  # noqa: BLE001
        print('webview   : MISSING —', exc)
    print('SELFTEST OK')


def _run_pywebview(url: str) -> bool:
    """Native window via pywebview/WebView2. Returns True if it ran (and the
    window has since closed), False if the backend is unavailable so the caller
    can fall back. Blocks until the window is closed."""
    try:
        import webview
    except Exception:  # noqa: BLE001 — not bundled / import error
        logger.info('pywebview not available; falling back')
        return False
    try:
        webview.create_window('Alpha POS', url, width=1060, height=760,
                              min_size=(900, 640))
        # Blocks until the window closes. Raises if WebView2 can't initialize.
        webview.start()
        return True
    except Exception:  # noqa: BLE001 — WebView2 runtime missing / init failed
        logger.exception('pywebview window failed; falling back to Edge/browser')
        return False


def _run_edge(url: str) -> bool:
    """Chromeless Edge "--app" window. Returns True if launched (and has since
    closed), False if Edge isn't present."""
    edge = _find_edge()
    if not edge:
        return False
    proc = subprocess.Popen([
        edge, f'--app={url}', f'--user-data-dir={_profile_dir()}',
        '--no-first-run', '--no-default-browser-check', '--window-size=1040,740',
    ])
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    return True


def _autostart_backend():
    """Bring the POS server up automatically on launch and keep it up.

    Runs in the background so the panel appears immediately. Does the (idempotent)
    first-run install, starts the server, and supervises it forever — retrying
    with backoff if a start fails and restarting it if it dies. This is what
    makes every boot/login come up serving with no button press.
    """
    api = control_server._API
    try:
        api.run_setup()  # migrate + bootstrap admin + collectstatic (idempotent)
    except Exception:  # noqa: BLE001 — still try to start with whatever exists
        logger.exception('autostart: first-run setup failed')

    backoff = 3
    while True:
        try:
            if not api.server.is_running():
                res = api.start_server()
                if res.get('running'):
                    logger.info('autostart: POS server up — LAN %s', api.server.url())
                    backoff = 3
                else:
                    logger.error('autostart: start failed: %s', res.get('error'))
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
        except Exception:  # noqa: BLE001 — never let the supervisor die
            logger.exception('autostart: start raised')
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        time.sleep(5)  # watchdog poll — restart promptly if the server stops


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')

    if '--selftest' in sys.argv:
        return _selftest()

    # Load saved config + baked defaults (incl. ALPHA_POS_UPDATE_URL) into the
    # process env BEFORE the self-update check — otherwise apply_env_to_process
    # only runs later inside ensure_django, so the launch-time updater would see
    # no update server and skip on a hands-off boot.
    try:
        from desktop import config_store
        config_store.apply_env_to_process()
    except Exception:  # noqa: BLE001 — never let env loading block startup
        logger.exception('early env load failed; continuing')

    # Self-update check BEFORE anything binds or serves. In a configured frozen
    # build this may download a new signed bundle and restart the process (so
    # the call won't return); in dev or when unconfigured it's a guaranteed
    # no-op that never raises. --no-update skips it (useful for debugging).
    if '--no-update' not in sys.argv:
        try:
            from desktop import updater
            updater.check_and_apply()
            # Reached here => no update applied; confirm any prior update booted
            # cleanly so its pending marker is cleared.
            updater.mark_started_ok()
        except Exception:  # noqa: BLE001 — never let updating block startup
            logger.exception('self-update check failed; continuing')

    url = f'http://{control_server.CONTROL_HOST}:{control_server.CONTROL_PORT}/'

    # Single-instance: if the control port is already bound, another copy is
    # running — just surface its window and exit instead of crashing on bind.
    try:
        httpd = control_server.serve()
    except OSError:
        if not _run_pywebview(url) and not _run_edge(url):
            webbrowser.open(url)
        return

    threading.Thread(target=httpd.serve_forever, name='control', daemon=True).start()
    time.sleep(0.4)  # let the socket bind

    # Auto-start + supervise the POS backend so every launch comes up serving
    # on the LAN by itself, with retries — no operator button press needed.
    threading.Thread(target=_autostart_backend, name='autostart', daemon=True).start()

    # Show the panel. Prefer the native window; fall back so it ALWAYS appears.
    forced_browser = '--browser' in sys.argv
    shown = False
    if not forced_browser:
        shown = _run_pywebview(url) or _run_edge(url)
    if not shown:
        webbrowser.open(url)
        print(f'Opened {url} in the default browser. Close this window to exit.')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    # Window closed → stop the POS server (if running) and exit.
    try:
        control_server._API.stop_server()
    except Exception:  # noqa: BLE001
        pass
    httpd.shutdown()
    sys.exit(0)


if __name__ == '__main__':
    main()
