"""Runs the Django POS server in-process via waitress, in a background thread.

Keeping the server in the same process as the GUI means one .exe, no child
python to ship, and the control panel can call Django services directly for the
self-tests. Start/stop is controlled by the big button in the UI.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger('desktop.server')


class ServerManager:
    def __init__(self):
        self._server = None
        self._thread = None
        self._django_ready = False
        self._last_error = ''
        self.host = '127.0.0.1'
        self.port = 8000

    # -- Django bootstrap (idempotent) --------------------------------------
    def ensure_django(self):
        if self._django_ready:
            return
        from desktop import config_store
        config_store.apply_env_to_process()
        self.port = int(config_store.parse_env_file().get('PORT', '8000') or 8000)

        import django
        django.setup()
        self._django_ready = True

    def first_time_install(self, log=lambda m: None):
        """Run migrations, bootstrap the admin, and collect static — the
        'install everything on first run' step. Safe to re-run."""
        self.ensure_django()
        from django.core.management import call_command
        log('Applying database migrations…')
        call_command('migrate', '--noinput', verbosity=0)
        log('Creating admin account (if missing)…')
        try:
            call_command('bootstrap_admin', verbosity=0)
        except Exception as exc:  # noqa: BLE001
            log(f'  (bootstrap_admin skipped: {exc})')
        log('Collecting static files…')
        try:
            call_command('collectstatic', '--noinput', verbosity=0)
        except Exception as exc:  # noqa: BLE001
            log(f'  (collectstatic skipped: {exc})')
        log('Setup complete.')

    # -- Server lifecycle ----------------------------------------------------
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return {'running': True, 'message': 'Server already running'}
        try:
            self.ensure_django()
            from waitress import create_server
            from alpha_pos.wsgi import application

            self._server = create_server(application, host=self.host, port=self.port)
            self._thread = threading.Thread(
                target=self._server.run, name='waitress', daemon=True,
            )
            self._thread.start()
            self._last_error = ''
            logger.info('POS server started on http://%s:%s', self.host, self.port)
            return {'running': True, 'url': self.url(), 'message': 'Server started'}
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            logger.exception('server start failed')
            return {'running': False, 'error': str(exc)}

    def stop(self):
        if self._server is not None:
            try:
                self._server.close()
            except Exception:  # noqa: BLE001
                logger.exception('server close failed')
        self._server = None
        self._thread = None
        return {'running': False, 'message': 'Server stopped'}

    def url(self):
        return f'http://{self.host}:{self.port}'

    def status(self):
        return {
            'running': self.is_running(),
            'url': self.url(),
            'django_ready': self._django_ready,
            'last_error': self._last_error,
        }
