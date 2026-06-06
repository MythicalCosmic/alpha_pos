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
        try:
            self.server.ensure_django()
            # Fiscal mode is a live cache toggle — applies without a restart.
            from fiscalization.config import FiscalConfig
            mode = clean.get('FISCALIZATION_MODE')
            if mode:
                FiscalConfig.set_mode(mode)
            # Telegram token + chat ids go into the DB-backed NotificationSettings
            # (the canonical source TelegramAPI reads) so messages deliver
            # immediately — no restart, unlike the .env-only settings.
            token = clean.get('TELEGRAM_BOT_TOKEN')
            chat_raw = clean.get('TELEGRAM_CHAT_IDS')
            if (token and token != '••••••••') or chat_raw is not None:
                from notifications.models import NotificationSettings
                ns = NotificationSettings.load()
                if token and token != '••••••••':
                    ns.bot_token = token.strip()
                if chat_raw is not None:
                    ns.chat_ids = [c.strip() for c in str(chat_raw)
                                   .replace(' ', ',').split(',') if c.strip()]
                ns.save()
            # Sync settings are read from `settings` at call time, so apply them
            # to the live settings object — no app restart needed to test sync.
            from django.conf import settings as _dj
            for key in ('CLOUD_SYNC_URL', 'CLOUD_SYNC_TOKEN', 'BRANCH_ID', 'DEPLOYMENT_MODE'):
                if key in clean and clean[key] is not None:
                    setattr(_dj, key, clean[key])
            if 'SYNC_ENABLED' in clean:
                from base.services.sync.config import SyncConfig
                en = str(clean['SYNC_ENABLED']).lower() in ('true', '1', 'yes')
                _dj.SYNC_ENABLED = en
                SyncConfig.enable() if en else SyncConfig.disable()
        except Exception:  # noqa: BLE001
            logger.exception('live config apply failed')
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

    # -- cloud sync (this branch <-> the cloud hub) --------------------------
    @_safe
    def cloud_status(self):
        """Sync config + whether the cloud hub is reachable right now."""
        self.server.ensure_django()
        from base.services.sync.config import SyncConfig, get_cloud_url
        from base.services.sync import transport
        cfg = SyncConfig.get_status()
        reachable = bool(get_cloud_url()) and transport.check_health()
        return {'ok': True, 'config': cfg, 'reachable': reachable}

    @_safe
    def cloud_test_connection(self):
        """Ping the cloud hub's /health over the configured CLOUD_SYNC_URL."""
        self.server.ensure_django()
        from base.services.sync import transport
        from base.services.sync.config import get_cloud_url
        url = get_cloud_url()
        if not url:
            return {'ok': False, 'error': 'CLOUD_SYNC_URL not set (Configuration tab)'}
        ok = transport.check_health()
        return {'ok': ok, 'reachable': ok, 'url': url,
                'message': 'reachable' if ok else 'unreachable'}

    @_safe
    def cloud_make_test_category(self, name=None):
        """Create a local Category so there's a real record to push up."""
        self.server.ensure_django()
        from base.models import Category
        from django.conf import settings
        branch = getattr(settings, 'BRANCH_ID', 'main') or 'main'
        nm = name or 'Desktop sync test'
        cat = Category.objects.create(name=nm, branch_id=branch)
        return {'ok': True, 'uuid': str(cat.uuid), 'name': nm, 'branch_id': branch}

    @_safe
    def cloud_push(self):
        """Push all unsynced local records up to the cloud hub."""
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        return {'ok': True, 'result': SyncService.push()}

    @_safe
    def cloud_pull(self):
        """Pull changes from the cloud hub down into this branch."""
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        return {'ok': True, 'result': SyncService.pull_from_cloud()}

    # -- telegram / notifications -------------------------------------------
    @_safe
    def telegram_test(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        # send_message returns (ok, error) — a REAL send to api.telegram.org.
        ok, err = TelegramAPI.send_message('✅ Alpha POS test message from the control panel.')
        return {'ok': bool(ok), 'error': err}

    @_safe
    def send_fake_notification(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        text = ('🧾 <b>TEST notification</b>\n\nOrder #TEST paid: 60 000 soʼm\n'
                'This is a fake notification from the control panel.')
        ok, err = TelegramAPI.send_message(text)
        return {'ok': bool(ok), 'error': err}

    @_safe
    def get_telegram(self):
        self.server.ensure_django()
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        return {'ok': True, 'bot_token_set': bool(ns.bot_token), 'chat_ids': ns.chat_ids}

    # -- notifications: admin telegram config + message layouts -------------
    @_safe
    def notif_settings(self):
        self.server.ensure_django()
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        return {'ok': True, 'bot_token_set': bool(ns.bot_token),
                'chat_ids': ns.chat_ids, 'brand_name': getattr(ns, 'brand_name', '')}

    @_safe
    def save_notif_settings(self, bot_token=None, chat_ids=None, brand_name=None):
        self.server.ensure_django()
        from django.core.cache import cache
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        if bot_token and bot_token != '••••••••':
            ns.bot_token = bot_token.strip()
        if chat_ids is not None:
            if isinstance(chat_ids, str):
                chat_ids = [c.strip() for c in chat_ids.replace(' ', ',').split(',') if c.strip()]
            ns.chat_ids = chat_ids
        if brand_name is not None:
            ns.brand_name = brand_name
        ns.save()
        try:
            cache.delete(getattr(NotificationSettings, '_CACHE_KEY', 'notif:settings:v1'))
        except Exception:
            pass
        return {'ok': True}

    @_safe
    def list_templates(self):
        """All Telegram/notification message layouts, editable."""
        self.server.ensure_django()
        from notifications.models import NotificationTemplate
        rows = [{
            'id': t.id, 'notification_type': t.notification_type, 'name': t.name,
            'template_text': t.template_text, 'description': t.description,
            'is_enabled': t.is_enabled, 'language': t.language,
        } for t in NotificationTemplate.objects.all()]
        return {'ok': True, 'templates': rows}

    @_safe
    def save_template(self, template_id, template_text, is_enabled=True):
        self.server.ensure_django()
        from django.core.cache import cache
        from notifications.models import NotificationTemplate
        from notifications.services.safe_format import validate_template_text
        err = validate_template_text(template_text)
        if err:
            return {'ok': False, 'error': err}
        t = NotificationTemplate.objects.filter(id=template_id).first()
        if not t:
            return {'ok': False, 'error': 'template not found'}
        t.template_text = template_text
        t.is_enabled = bool(is_enabled)
        t.save()
        try:
            cache.delete(f'notif:template:{t.notification_type}')
        except Exception:
            pass
        return {'ok': True}

    @_safe
    def preview_template(self, template_text):
        self.server.ensure_django()
        import string
        from notifications.services.safe_format import validate_template_text, safe_format
        err = validate_template_text(template_text)
        if err:
            return {'ok': False, 'error': err}
        samples = {'order_id': 'A-0042', 'display_id': 'A-0042', 'total': '60 000',
                   'amount': '60 000', 'customer': 'Akmal', 'name': 'Akmal',
                   'status': 'READY', 'branch': 'Main', 'phone': '+998 90 123 45 67',
                   'brand_name': 'My Cafe', 'time': '14:32', 'date': '2026-06-05',
                   'cashier': 'Dilnoza', 'table': '7', 'points': '12'}
        ctx = {}
        for _l, f, _s, _c in string.Formatter().parse(template_text):
            if f:
                ctx[f] = samples.get(f, f.upper())
        try:
            return {'ok': True, 'rendered': safe_format(template_text, **ctx)}
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': str(exc)}

    @_safe
    def admin_credentials(self):
        """The first-admin login the app created on this PC, so the operator can
        sign in to the POS / admin panel. Stored locally (the GUI exe has no
        console where the bootstrap banner would appear)."""
        creds = config_store.read_admin_creds()
        return {'ok': True, 'email': creds.get('email', ''),
                'password': creds.get('password', ''), 'set': bool(creds.get('email'))}

    @_safe
    def admin_url(self):
        """The Django admin — full CRUD over every backend model (products,
        users, stock, loyalty, queue, ...)."""
        return {'ok': True, 'url': self.server.url() + '/admin/',
                'running': self.server.is_running()}

    @_safe
    def create_django_admin(self, username='admin', password='', email=''):
        """Create (or reset) the Django /admin/ superuser for this PC so the
        'Open full admin panel' button has a login. This is the Django auth
        user (username-based), separate from the POS app admin (email-based)."""
        if not username or not password:
            return {'ok': False, 'error': 'username and password are required'}
        self.server.ensure_django()
        # Make sure the auth tables exist even if Start was never pressed.
        try:
            from django.core.management import call_command
            call_command('migrate', '--noinput', verbosity=0)
        except Exception:  # noqa: BLE001
            logger.exception('migrate before admin create failed')
        from django.contrib.auth import get_user_model
        User = get_user_model()
        u = User.objects.filter(username=username).first()
        if u:
            u.set_password(password)
            u.is_staff = u.is_superuser = u.is_active = True
            u.save()
            return {'ok': True, 'created': False, 'username': username,
                    'message': 'password reset'}
        User.objects.create_superuser(username=username, email=email or '', password=password)
        return {'ok': True, 'created': True, 'username': username}

    # -- license / subscription ---------------------------------------------
    @_safe
    def license_register(self, email, plan_id=None):
        """Register this install against the control center (online). Requires
        LICENSE_CONTROL_CENTER_URL — returns its error if not configured."""
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.register(email, plan_id)
        return {'ok': bool(body.get('success')), 'status': status, 'data': body}

    @_safe
    def license_plans(self):
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.list_plans()
        return {'ok': status == 200, 'status': status, 'data': body}

    @_safe
    def license_plan_change(self, plan_id, note=''):
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.request_plan_change(plan_id, note)
        return {'ok': status in (200, 201) or bool(body.get('success')),
                'status': status, 'data': body}

    @_safe
    def license_heartbeat_now(self):
        self.server.ensure_django()
        from licensing.services.heartbeat import do_heartbeat
        body, status = do_heartbeat()
        return {'ok': status == 200, 'status': status, 'data': body}

    @_safe
    def license_activate_offline(self, email='', org='', expires=''):
        """Interim activation with no control center: flips the license ACTIVE
        locally. expires='' means a perpetual license (explicit)."""
        self.server.ensure_django()
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('activate_offline', stdout=out, email=email or '', org=org or '',
                     expires=expires or '', perpetual=not bool(expires), deactivate=False)
        return {'ok': True, 'output': out.getvalue().strip()}

    @_safe
    def license_deactivate(self):
        self.server.ensure_django()
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('activate_offline', stdout=out, deactivate=True,
                     email='', org='', expires='', perpetual=False)
        return {'ok': True, 'output': out.getvalue().strip()}

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
