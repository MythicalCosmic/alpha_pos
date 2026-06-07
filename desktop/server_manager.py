"""Runs the Django POS server in-process via waitress, in a background thread.

Keeping the server in the same process as the GUI means one .exe, no child
python to ship, and the control panel can call Django services directly for the
self-tests. Start/stop is controlled by the big button in the UI.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger('desktop.server')


class ServerManager:
    def __init__(self):
        self._server = None
        self._thread = None
        self._django_ready = False
        self._last_error = ''
        # Bind to every interface so the whole LAN (other monoblocks /
        # cashier terminals) can reach the POS, not just this machine.
        self.host = '0.0.0.0'
        self.port = 8000
        self._sync_thread = None
        self._sync_stop = False
        self._hb_thread = None
        self._hb_stop = False

    # -- Automatic license heartbeat ----------------------------------------
    def _ensure_heartbeat_worker(self):
        """Phone home to the control center every LICENSE_HEARTBEAT_INTERVAL so
        the license/billing verdict (active/suspended/expired) stays fresh
        without the operator clicking. Self-gates: do_heartbeat() is a no-op
        when no control-center URL is configured (offline-activated installs)."""
        if self._hb_thread is not None and self._hb_thread.is_alive():
            return
        self._hb_stop = False
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, name='license-heartbeat', daemon=True)
        self._hb_thread.start()
        logger.info('heartbeat worker started')

    def _heartbeat_loop(self):
        from django.conf import settings as dj
        from django.db import close_old_connections
        first = True
        while not self._hb_stop:
            delay = 20 if first else max(
                60, int(getattr(dj, 'LICENSE_HEARTBEAT_INTERVAL', 300) or 300))
            first = False
            for _ in range(delay):
                if self._hb_stop:
                    return
                time.sleep(1)
            try:
                from licensing.services.heartbeat import do_heartbeat
                do_heartbeat()  # no-op without LICENSE_CONTROL_CENTER_URL
            except Exception:  # noqa: BLE001 — never let the worker die
                logger.exception('heartbeat worker iteration failed')
            finally:
                # Release this thread's DB connection each cycle — see the note
                # in _sync_loop. License.load() runs queries here.
                close_old_connections()

    # -- Automatic background sync ------------------------------------------
    def _ensure_sync_worker(self):
        """Start a daemon that pushes (and pulls) every SYNC_INTERVAL whenever
        sync is enabled, so records reach the cloud hands-free — no button
        press. Idempotent; the loop self-gates when sync is off."""
        if self._sync_thread is not None and self._sync_thread.is_alive():
            return
        self._sync_stop = False
        self._sync_thread = threading.Thread(
            target=self._sync_loop, name='sync-worker', daemon=True)
        self._sync_thread.start()
        logger.info('sync worker started')

    def _sync_loop(self):
        from django.db import close_old_connections
        from base.services.sync.config import (
            SyncConfig, get_sync_interval, is_local_mode, get_pull_enabled,
            get_cloud_url,
        )
        from base.services.sync.service import SyncService
        while not self._sync_stop:
            interval = max(10, get_sync_interval())
            for _ in range(interval):  # responsive to stop without long sleeps
                if self._sync_stop:
                    return
                time.sleep(1)
            try:
                if SyncConfig.is_enabled() and is_local_mode() and get_cloud_url():
                    SyncService.push()
                    if get_pull_enabled():
                        SyncService.pull_from_cloud()
            except Exception:  # noqa: BLE001 — never let the worker die
                logger.exception('sync worker iteration failed')
            finally:
                # This daemon thread runs ORM queries outside Django's
                # request cycle, so the request_finished signal never fires to
                # release its DB connection. Without this the connection stays
                # pinned for the life of the process — on SQLite it holds a
                # WAL/writer slot (worsening "database is locked" for LAN
                # terminals), on Postgres it accumulates toward "too many
                # clients". Close it each cycle; the next iteration reopens.
                close_old_connections()

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
            from desktop import config_store
            from base.models import User
            # On a fresh DB we choose the admin password ourselves and persist it,
            # so the panel can show it — the GUI exe has no console where
            # bootstrap_admin's banner would otherwise print it.
            if not User.objects.exists():
                email = 'admin@local'
                password = config_store.generate_password()
                call_command('bootstrap_admin', email=email, password=password, verbosity=0)
                config_store.write_admin_creds(email, password)
                log(f'  Admin created — email: {email}  (password shown in the panel)')
            else:
                call_command('bootstrap_admin', verbosity=0)
        except Exception as exc:  # noqa: BLE001
            log(f'  (bootstrap_admin skipped: {exc})')
        log('Seeding notification templates…')
        try:
            # Idempotent (get_or_create) — without this the templates table is
            # empty and automatic Telegram notifications silently no-op.
            call_command('seed_templates', verbosity=0)
        except Exception as exc:  # noqa: BLE001
            log(f'  (seed_templates skipped: {exc})')
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
            self._ensure_sync_worker()  # auto-push/pull when sync is enabled
            self._ensure_heartbeat_worker()  # keep the license verdict fresh
            self._last_error = ''
            logger.info('POS server bound on 0.0.0.0:%s — reachable on the LAN at %s',
                        self.port, self.url())
            return {'running': True, 'url': self.url(),
                    'lan_url': self.url(), 'lan_ip': self.lan_ip(),
                    'message': 'Server started'}
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

    @staticmethod
    def lan_ip():
        """This machine's primary LAN IP — the address other devices use to
        reach the POS. Falls back to 127.0.0.1 if offline."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No packets are actually sent; this just selects the outbound
            # interface so getsockname() returns the real LAN IP.
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except Exception:  # noqa: BLE001
            return '127.0.0.1'
        finally:
            s.close()

    def url(self):
        # The address OTHER devices use — the LAN IP, not the 0.0.0.0 bind addr.
        return f'http://{self.lan_ip()}:{self.port}'

    def status(self):
        return {
            'running': self.is_running(),
            'url': self.url(),
            'lan_ip': self.lan_ip(),
            'port': self.port,
            'django_ready': self._django_ready,
            'last_error': self._last_error,
        }
