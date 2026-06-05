"""Tiny localhost control server for the desktop panel.

Serves the control-panel UI (desktop/ui/index.html) and a JSON API that
dispatches to bridge.Api methods. It runs on 127.0.0.1:CONTROL_PORT and is
SEPARATE from the POS server (waitress on 8000) so the panel survives the
operator starting/stopping the POS server with the big button.

The GUI is the same HTML rendered in a chromeless Edge "--app" window (works on
any Python; no pywebview, which has no Python 3.14 wheels yet).
"""
from __future__ import annotations

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from desktop.bridge import Api

logger = logging.getLogger('desktop.control')

CONTROL_HOST = '127.0.0.1'
CONTROL_PORT = 8765

_API = Api()


def _ui_dir() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    cand = base / 'desktop' / 'ui'
    return cand if cand.exists() else (Path(__file__).resolve().parent / 'ui')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default stderr noise
        pass

    def _send(self, code, body, ctype='application/json'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            html = (_ui_dir() / 'index.html').read_text(encoding='utf-8')
            return self._send(200, html, 'text/html; charset=utf-8')
        if self.path == '/healthz':
            return self._send(200, 'ok', 'text/plain')
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.path.startswith('/api/'):
            return self._send(404, '{"error":"not found"}')
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
