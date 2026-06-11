"""Tiny localhost control server for the desktop panel.

Serves the control-panel UI (desktop/ui/index.html) and a JSON API that
dispatches to bridge.Api methods. It runs on 127.0.0.1:CONTROL_PORT and is
SEPARATE from the POS server (waitress on 8000) so the panel survives the
operator starting/stopping the POS server with the big button.

The GUI is the same HTML rendered in a chromeless Edge "--app" window (works on
any Python; no pywebview, which has no Python 3.14 wheels yet).

SECURITY: the API is on a localhost TCP port, which any web page the operator
visits could try to POST to (CSRF / DNS-rebinding against the bridge). Two
defenses: (1) every /api/ call must carry the per-process session token that is
injected only into the UI we serve; (2) the Host header must be our own
loopback host:port, so a rebound DNS name (evil.com -> 127.0.0.1) is rejected.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from desktop.bridge import Api

logger = logging.getLogger('desktop.control')

CONTROL_HOST = '127.0.0.1'
CONTROL_PORT = 8765

# Per-launch secret. Injected into the served HTML and required as a header on
# every /api/ call, so a random page in the operator's browser cannot drive the
# bridge through the localhost port.
CONTROL_TOKEN = secrets.token_urlsafe(32)
_ALLOWED_HOSTS = {f'{CONTROL_HOST}:{CONTROL_PORT}', f'localhost:{CONTROL_PORT}'}

_API = Api()


def _ui_dir() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    cand = base / 'desktop' / 'ui'
    return cand if cand.exists() else (Path(__file__).resolve().parent / 'ui')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default stderr noise
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get('Host') or '').strip().lower()
        return host in _ALLOWED_HOSTS

    def _send(self, code, body, ctype='application/json'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        # No-store: this panel exposes config/secrets; never let a proxy cache it.
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    # Static assets the panel pulls in (CSS, vendored React/Babel, the app/*.jsx
    # Babel fetches at runtime). JSX is served as text/babel so the in-browser
    # compiler picks it up.
    _CTYPES = {
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.jsx': 'text/babel; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.map': 'application/json; charset=utf-8',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
        '.ico': 'image/x-icon',
        '.woff2': 'font/woff2',
        '.woff': 'font/woff',
    }

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, '{"error":"forbidden host"}')
        if self.path in ('/', '/index.html'):
            html = (_ui_dir() / 'index.html').read_text(encoding='utf-8')
            html = html.replace('{{CONTROL_TOKEN}}', CONTROL_TOKEN)
            return self._send(200, html, 'text/html; charset=utf-8')
        if self.path == '/healthz':
            return self._send(200, 'ok', 'text/plain')
        # Static panel assets — confined to the ui dir. A resolved path that
        # escapes it (.. traversal) or an unknown extension is refused.
        rel = self.path.split('?', 1)[0].lstrip('/')
        ext = os.path.splitext(rel)[1].lower()
        if rel and ext in self._CTYPES:
            ui = _ui_dir().resolve()
            target = (ui / rel).resolve()
            try:
                target.relative_to(ui)
            except ValueError:
                return self._send(403, '{"error":"forbidden path"}')
            if target.is_file():
                return self._send(200, target.read_bytes(), self._CTYPES[ext])
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, '{"error":"forbidden host"}')
        if not self.path.startswith('/api/'):
            return self._send(404, '{"error":"not found"}')
        # Reject cross-site / unauthorized callers before doing any work.
        if self.headers.get('X-Control-Token') != CONTROL_TOKEN:
            return self._send(403, json.dumps({'ok': False, 'error': 'forbidden'}))
        method = self.path[len('/api/'):].strip('/')
        fn = getattr(_API, method, None)
        if not callable(fn) or method.startswith('_'):
            return self._send(404, json.dumps({'ok': False, 'error': f'no method {method}'}))
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b'[]'
        try:
            args = json.loads(raw or b'[]')
            if not isinstance(args, list):
                args = [args]
        except ValueError:
            args = []
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 — never crash the panel
            logger.exception('control api %s failed', method)
            result = {'ok': False, 'error': str(exc)}
        self._send(200, json.dumps(result, default=str))


def serve(host=CONTROL_HOST, port=CONTROL_PORT):
    httpd = ThreadingHTTPServer((host, port), Handler)
    logger.info('control panel on http://%s:%s', host, port)
    return httpd
