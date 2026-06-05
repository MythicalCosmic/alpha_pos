"""Entry point for the Alpha POS desktop control panel.

    python -m desktop.app          # dev
    (or the packaged AlphaPOS.exe)

Starts the local control server, then opens the panel in a chromeless Edge
"--app" window (a native-feeling app window, no browser chrome). When the window
is closed, the POS server is stopped and the process exits.

Edge is pre-installed on Windows 10/11. If it isn't found we fall back to the
default browser.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from desktop import control_server


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
    print('SELFTEST OK')


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')

    if '--selftest' in sys.argv:
        return _selftest()

    httpd = control_server.serve()
    threading.Thread(target=httpd.serve_forever, name='control', daemon=True).start()
    time.sleep(0.4)  # let the socket bind

    url = f'http://{control_server.CONTROL_HOST}:{control_server.CONTROL_PORT}/'
    edge = _find_edge()
    if edge:
        # A dedicated user-data-dir forces a distinct Edge process we can wait
        # on, so closing the window exits the app.
        proc = subprocess.Popen([
            edge, f'--app={url}', f'--user-data-dir={_profile_dir()}',
            '--no-first-run', '--no-default-browser-check',
            '--window-size=1040,740',
        ])
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    else:
        webbrowser.open(url)
        print(f'Edge not found — opened {url} in the default browser. '
              'Close this console to exit.')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    # Window closed → stop the POS server (if running) and exit.
    try:
        control_server._API.stop_server()
    except Exception:
        pass
    httpd.shutdown()
    sys.exit(0)


if __name__ == '__main__':
    main()
