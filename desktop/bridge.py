"""The js_api bridge exposed to the GUI. Every method returns a JSON-friendly
dict and never raises (the UI shows {ok: false, error} instead of crashing the
window). Django services are imported lazily — after ensure_django()."""
from __future__ import annotations

import logging
import uuid as uuid_mod

from desktop import config_store
from desktop.server_manager import ServerManager

logger = logging.getLogger('desktop.bridge')


def _safe(fn):
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception as exc:  # noqa: BLE001
            logger.exception('bridge %s failed', fn.__name__)
            return {'ok': False, 'error': str(exc)}
    wrapper.__name__ = fn.__name__
    return wrapper


class Api:
    def __init__(self):
        self.server = ServerManager()

    # -- first run / config --------------------------------------------------
    @_safe
    def get_state(self):
        return {'ok': True, 'tos_accepted': config_store.tos_accepted(),
                'server': self.server.status()}

    @_safe
    def accept_tos(self):
        config_store.accept_tos()
        return {'ok': True}

    @_safe
    def get_config(self):
        cfg = config_store.read_config()
        # Mask secrets for display (operator can overwrite; blank = unchanged).
        masked = dict(cfg)
        for k in config_store.SECRET_KEYS:
            if masked.get(k):
                masked[k] = '••••••••'
        return {'ok': True, 'config': masked, 'secret_keys': sorted(config_store.SECRET_KEYS)}

    @_safe
    def save_config(self, values):
        # Don't overwrite a secret with the mask placeholder.
        current = config_store.read_config()
        clean = {}
        for k, v in (values or {}).items():
            if k in config_store.SECRET_KEYS and v in ('••••••••', None, ''):
                clean[k] = current.get(k, '')
            else:
                clean[k] = v
        config_store.write_config(clean)
        # Apply the fiscal mode live (cache toggle) so it takes effect without a
        # restart; other settings need a server restart (noted in the UI).
        try:
            self.server.ensure_django()
            from fiscalization.config import FiscalConfig
            mode = clean.get('FISCALIZATION_MODE')
            if mode:
                FiscalConfig.set_mode(mode)
        except Exception:  # noqa: BLE001
            logger.exception('live fiscal mode apply failed')
        return {'ok': True, 'restart_required': self.server.is_running()}

    # -- install + server lifecycle -----------------------------------------
    @_safe
    def run_setup(self):
        logs = []
        self.server.first_time_install(log=logs.append)
        return {'ok': True, 'logs': logs}

    @_safe
    def start_server(self):
        return {'ok': True, **self.server.start()}

    @_safe
    def stop_server(self):
        return {'ok': True, **self.server.stop()}

    @_safe
    def server_status(self):
        return {'ok': True, **self.server.status()}

    @_safe
    def test_server_connection(self):
        import urllib.request
        if not self.server.is_running():
            return {'ok': False, 'error': 'Server is not running'}
        url = self.server.url() + '/healthz'
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode('utf-8', 'replace')
        return {'ok': resp.status == 200, 'status': resp.status, 'body': body[:50]}

    # -- dashboards ----------------------------------------------------------
    @_safe
    def license_status(self):
        self.server.ensure_django()
        from licensing.models import License
        lic = License.load()
        return {'ok': True, 'license': {
            'status': lic.status,
            'org_name': getattr(lic, 'org_name', ''),
            'email': getattr(lic, 'email', ''),
            'expires_at': lic.expires_at.isoformat() if lic.expires_at else None,
            'last_heartbeat_at': lic.last_heartbeat_at.isoformat() if lic.last_heartbeat_at else None,
            'balance': str(lic.balance) if getattr(lic, 'balance', None) is not None else None,
            'days_remaining': getattr(lic, 'days_remaining', None),
            'last_message': getattr(lic, 'last_message', ''),
        }}

    @_safe
    def sync_status(self):
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        return {'ok': True, 'sync': SyncService.get_status()}

    @_safe
    def send_mock_sync(self):
        """Loopback: push a temp record through the receive pipeline, read it
        back, then remove it. Proves the sync machinery end-to-end with no
        cloud server. Leaves no junk behind."""
        self.server.ensure_django()
        from django.conf import settings
        from base.services.sync.receiver import CloudReceiver
        from base.models import Category
        branch = getattr(settings, 'BRANCH_ID', 'main') or 'main'
        u = str(uuid_mod.uuid4())
        record = {'uuid': u, 'sync_version': 1, 'is_deleted': False,
                  'name': 'MOCK SYNC TEST', 'branch_id': branch}
        result = CloudReceiver.receive_batch('category', branch, [record])
        readback = Category.objects.filter(uuid=u).first()
        found = readback is not None
        if readback:
            readback.delete(hard_delete=True)  # cleanup
        return {'ok': True, 'sent': record, 'received': {
            'created': result.get('created'), 'errors': result.get('errors'),
        }, 'read_back': found}

    @_safe
    def fetch_mock_sync(self):
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        from base.models import Category
        rows = SyncService.get_unsynced(Category)
        return {'ok': True, 'unsynced_categories': len(rows), 'sample': rows[:3]}

    # -- telegram / notifications -------------------------------------------
    @_safe
    def telegram_test(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        res = TelegramAPI.send_message('✅ Alpha POS test message from the control panel.')
        return {'ok': bool(res), 'result': bool(res)}

    @_safe
    def send_fake_notification(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        text = ('🧾 <b>TEST notification</b>\n\nOrder #TEST paid: 60 000 soʼm\n'
                'This is a fake notification from the control panel.')
        res = TelegramAPI.send_message(text)
        return {'ok': bool(res), 'sent': bool(res)}

    # -- fiscalization -------------------------------------------------------
    @_safe
    def fiscal_status(self):
        self.server.ensure_django()
        from fiscalization.services import FiscalizationService
        return {'ok': True, 'fiscal': FiscalizationService.stats()}

    @_safe
    def fiscal_set_mode(self, mode):
        self.server.ensure_django()
        from fiscalization.config import FiscalConfig
        FiscalConfig.set_mode(mode)
        return {'ok': True, 'mode': FiscalConfig.get_mode()}

    @_safe
    def fiscal_test(self):
        self.server.ensure_django()
        from fiscalization.config import FiscalConfig
        from fiscalization.providers import MockProvider
        payload = {'tin': FiscalConfig.tenant().get('tin') or '000000000',
                   'receipt_type': 'SALE', 'order_id': 'TEST', 'total': 5000000,
                   'items': [{'name': 'Test item', 'ikpu': '00000000000000000',
                              'price': 5000000, 'quantity': 1, 'vat_percent': 0, 'vat': 0}]}
        r = MockProvider(FiscalConfig.tenant()).fiscalize(payload)
        return {'ok': r.success, 'fiscal_sign': r.fiscal_sign, 'qr_url': r.qr_url,
                'fiscal_number': r.fiscal_number, 'error': r.error}
