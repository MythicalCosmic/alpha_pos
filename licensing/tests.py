"""Tests for the kill-switch middleware + URL allowlist + cache flow.

We exercise the middleware through the Django test client rather than
unit-testing it in isolation, because the position-of-MIDDLEWARE behavior
is the actual contract: a /healthz request must always pass, and a
business endpoint must 503 while UNREGISTERED.
"""
import pytest
from django.test import Client


pytestmark = pytest.mark.django_db


def _client():
    return Client()


def _unregister_license():
    """Reset the License row to UNREGISTERED, undoing conftest's
    autouse `_active_license` fixture for the duration of this test."""
    from licensing.models import License
    lic = License.load()
    lic.status = License.Status.UNREGISTERED
    lic.last_heartbeat_at = None
    lic.last_server_now = None
    lic.expires_at = None
    lic.save()


class TestMiddlewareAllowlist:
    """Allowlisted paths must work even when the license is UNREGISTERED
    (the default state on a freshly-installed POS — there is no License
    row yet, so .load() will create one with status=UNREGISTERED)."""

    def test_healthz_passes_without_license(self):
        _unregister_license()
        resp = _client().get('/healthz')
        assert resp.status_code == 200
        assert resp.content == b'ok'

    def test_status_endpoint_passes_without_license(self):
        _unregister_license()
        resp = _client().get('/api/licensing/status')
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        assert body['data']['status'] == 'UNREGISTERED'
        assert body['data']['is_blocked'] is True
        assert body['data']['reason'] == 'license_unregistered'

    def test_setup_endpoint_reachable_without_license(self):
        # Setup is allowlisted in the kill switch — must not 503. A
        # POST with no JSON body validly returns 400 (bad request) from
        # the view itself; the point of this test is that the middleware
        # didn't refuse it first.
        _unregister_license()
        resp = _client().post('/api/licensing/setup')
        assert resp.status_code != 503
        assert resp.status_code in (400, 422)

    def test_unlock_endpoint_reachable_without_license(self):
        _unregister_license()
        resp = _client().post('/api/licensing/unlock')
        assert resp.status_code == 501


class TestKillSwitch:
    """Non-allowlisted endpoints must 503 while UNREGISTERED, with a
    payload the client can switch on."""

    def test_business_endpoint_blocked_when_unregistered(self):
        _unregister_license()
        # Pick a representative business endpoint — anything under /api/
        # that isn't /api/licensing or /api/sync/health. The login view
        # accepts POSTs without auth, so it's a clean test target.
        resp = _client().post('/api/admins/auth-login')
        assert resp.status_code == 503
        body = resp.json()
        assert body['success'] is False
        assert body['code'] == 'license_unregistered'
        assert body['status'] == 'UNREGISTERED'
        assert 'message' in body

    def test_get_blocked_too(self):
        _unregister_license()
        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code == 503

    def test_options_passes_so_cors_preflight_works(self):
        # If we 503'd preflight, the browser would never send the real
        # request and the renderer couldn't even see the kill-switch
        # body. corsheaders runs before us; we just no-op on OPTIONS.
        _unregister_license()
        resp = _client().options('/api/admins/dashboard/today')
        assert resp.status_code != 503


class TestStateTransitions:
    """The middleware reads state from cache; when the License row
    flips, cache must bust so the next request sees the new status."""

    def test_active_license_unblocks_endpoints(self):
        from licensing.models import License
        from licensing.services import state as state_mod
        from django.utils import timezone
        from datetime import timedelta

        lic = License.load()
        lic.status = License.Status.ACTIVE
        lic.last_heartbeat_at = timezone.now()
        lic.last_server_now = timezone.now()
        lic.expires_at = timezone.now() + timedelta(days=30)
        lic.org_name = 'Test Cafe'
        lic.email = 'owner@test.local'
        lic.save()

        # save() busts the cache; next request rebuilds and sees ACTIVE.
        snapshot = state_mod.get_state()
        assert snapshot.status == 'ACTIVE'
        assert snapshot.is_blocked() is False

        # No business endpoint should refuse now (this one returns 401 for
        # missing creds — that's the point: we got past licensing).
        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code != 503

    def test_suspended_license_blocks_immediately(self):
        from licensing.models import License
        from django.utils import timezone

        lic = License.load()
        lic.status = License.Status.SUSPENDED
        lic.last_heartbeat_at = timezone.now()
        lic.last_server_now = timezone.now()
        lic.save()

        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code == 503
        assert resp.json()['code'] == 'license_suspended'

    def test_offline_grace_exceeded_blocks(self):
        from licensing.models import License
        from django.utils import timezone
        from datetime import timedelta

        # Active status but last heartbeat is 10 days ago — beyond the
        # default 7-day grace window. Should block.
        lic = License.load()
        lic.status = License.Status.ACTIVE
        lic.last_heartbeat_at = timezone.now() - timedelta(days=10)
        lic.last_server_now = timezone.now() - timedelta(days=10)
        lic.save()

        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code == 503
        assert resp.json()['code'] == 'license_offline_grace_exceeded'

    def test_perpetual_unlock_overrides_everything(self):
        from licensing.models import License

        lic = License.load()
        lic.status = License.Status.PERPETUAL_UNLOCK
        lic.save()

        # PERPETUAL_UNLOCK means "vendor disappeared, escape hatch active"
        # — no expiry, no grace, never blocked.
        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code != 503


class TestMiddlewarePositionAssertion:
    """If a future refactor moves the middleware out of its slot, boot
    must fail loudly. We exercise AppConfig.ready() by re-importing it
    under a modified settings.MIDDLEWARE."""

    def test_missing_middleware_raises(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured
        from licensing.apps import LicensingConfig

        monkeypatch.setattr(
            'django.conf.settings.MIDDLEWARE',
            ['corsheaders.middleware.CorsMiddleware'],  # licensing absent
        )
        config = LicensingConfig.create('licensing')
        with pytest.raises(ImproperlyConfigured):
            config.ready()

    def test_middleware_before_cors_raises(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured
        from licensing.apps import LicensingConfig

        monkeypatch.setattr(
            'django.conf.settings.MIDDLEWARE',
            [
                'licensing.middleware.LicenseEnforcementMiddleware',
                'corsheaders.middleware.CorsMiddleware',
            ],
        )
        config = LicensingConfig.create('licensing')
        with pytest.raises(ImproperlyConfigured):
            config.ready()


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stand-in for requests.Response used by the heartbeat client."""
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = ''
    def json(self):
        return self._body


class TestSetupWizard:
    """The setup wizard must (a) refuse anything but UNREGISTERED,
    (b) validate the payload, (c) relay control-center errors with the
    original status code, (d) on success persist the key encrypted and
    flip to ACTIVE."""

    def _setup(self, payload):
        return _client().post(
            '/api/licensing/setup',
            data=__import__('json').dumps(payload),
            content_type='application/json',
        )

    def test_refuses_when_already_active(self):
        # Conftest fixture leaves the License in ACTIVE state.
        resp = self._setup({
            'email': 'a@b.local', 'org_name': 'X', 'invite_code': 'whatever',
        })
        assert resp.status_code == 409
        body = resp.json()
        assert body['code'] == 'already_registered'

    def test_missing_fields_returns_422(self):
        _unregister_license()
        resp = self._setup({'email': 'a@b.local'})
        assert resp.status_code == 422
        assert set(resp.json()['errors']) == {'org_name', 'invite_code'}

    def test_invalid_json_returns_400(self):
        _unregister_license()
        resp = _client().post(
            '/api/licensing/setup', data='not json',
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_control_center_url_missing_returns_503(self, settings):
        _unregister_license()
        settings.LICENSE_CONTROL_CENTER_URL = ''
        resp = self._setup({
            'email': 'a@b.local', 'org_name': 'X', 'invite_code': 'x',
        })
        assert resp.status_code == 503
        assert resp.json()['code'] == 'control_center_url_missing'

    def test_control_center_unreachable_returns_502(self, settings, monkeypatch):
        import requests
        _unregister_license()
        settings.LICENSE_CONTROL_CENTER_URL = 'http://does-not-exist.local'

        def _boom(*args, **kwargs):
            raise requests.ConnectionError('refused')

        monkeypatch.setattr('licensing.services.heartbeat.requests.post', _boom)
        resp = self._setup({
            'email': 'a@b.local', 'org_name': 'X', 'invite_code': 'x',
        })
        assert resp.status_code == 502
        assert resp.json()['code'] == 'control_center_unreachable'

    def test_control_center_404_passes_through(self, settings, monkeypatch):
        _unregister_license()
        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'

        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(404, {
                'success': False, 'message': 'Unknown invite code',
            }),
        )
        resp = self._setup({
            'email': 'a@b.local', 'org_name': 'X', 'invite_code': 'fake',
        })
        assert resp.status_code == 404

    def test_happy_path_activates_license_and_encrypts_key(
        self, settings, monkeypatch,
    ):
        from licensing.models import License
        from licensing.services import crypto

        _unregister_license()
        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'

        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(201, {
                'success': True,
                'key': 'fake-license-key-for-tests-' + 'x' * 40,
                'tenant_id': 7,
                'expires_at': None,
                'issued_at': '2026-05-23T10:00:00+00:00',
            }),
        )

        resp = self._setup({
            'email': 'Owner@Plov.uz',  # case folded by the view
            'org_name': 'Plov Plus',
            'invite_code': 'invite123',
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body['success'] is True
        # CRITICAL: the wizard response NEVER includes the key.
        assert 'key' not in body
        assert 'license' in body
        assert body['license']['status'] == 'ACTIVE'

        # DB row should be ACTIVE, key encrypted (not cleartext), email
        # lowercased.
        lic = License.load()
        assert lic.status == 'ACTIVE'
        assert lic.email == 'owner@plov.uz'
        assert lic.org_name == 'Plov Plus'
        assert lic.key_encrypted  # bytes blob present
        assert b'fake-license-key' not in bytes(lic.key_encrypted)
        # Roundtrip through Fernet returns the original cleartext.
        decrypted = crypto.decrypt_key(lic.key_encrypted)
        assert decrypted.startswith('fake-license-key')
        # last_heartbeat_at populated so the grace window starts now.
        assert lic.last_heartbeat_at is not None

        # And the kill switch should now LET requests through.
        resp2 = _client().get('/api/admins/dashboard/today')
        assert resp2.status_code != 503


class TestCryptoRoundtrip:
    def test_encrypt_decrypt_roundtrip(self):
        from licensing.services import crypto
        secret = 'super-secret-license-key-abcdef'
        blob = crypto.encrypt_key(secret)
        assert secret.encode() not in bytes(blob)
        assert crypto.decrypt_key(blob) == secret

    def test_empty_input(self):
        from licensing.services import crypto
        assert crypto.encrypt_key('') == b''
        assert crypto.decrypt_key(b'') is None

    def test_tampered_blob_returns_none(self):
        from licensing.services import crypto
        blob = crypto.encrypt_key('hello')
        assert crypto.decrypt_key(blob[:-1] + b'X') is None


# ---------------------------------------------------------------------------
# Heartbeat client
# ---------------------------------------------------------------------------


class TestHeartbeatClient:
    """Unit tests for `do_heartbeat` against a mocked control center.

    The real HTTP path is exercised end-to-end in the verification plan
    (both projects running side by side); here we just confirm each
    response code drives the License row the right way."""

    def _prep_active_with_key(self, settings):
        """Set up a License row that's ACTIVE with an encrypted key. The
        autouse fixture only sets ACTIVE without a real key, so heartbeats
        would fail decryption."""
        from licensing.models import License
        from licensing.services import crypto
        from django.utils import timezone
        from datetime import timedelta

        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'
        lic = License.load()
        lic.status = License.Status.ACTIVE
        lic.key_encrypted = crypto.encrypt_key(
            'live-license-key-aaaaaaaaaaaaaaaaaaaaa',
        )
        lic.email = 'demo@x.local'
        lic.org_name = 'Demo'
        lic.last_heartbeat_at = timezone.now() - timedelta(minutes=5)
        lic.expires_at = timezone.now() + timedelta(days=30)
        lic.save()
        return lic

    def test_unregistered_returns_304(self, settings):
        from licensing.services import heartbeat as hb
        _unregister_license()
        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'
        body, status = hb.do_heartbeat()
        assert status == 304

    def test_perpetual_unlock_returns_304(self, settings):
        from licensing.models import License
        from licensing.services import heartbeat as hb
        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'
        lic = License.load()
        lic.status = License.Status.PERPETUAL_UNLOCK
        lic.save()
        body, status = hb.do_heartbeat()
        assert status == 304

    def test_url_missing_returns_503(self, settings):
        from licensing.services import heartbeat as hb
        settings.LICENSE_CONTROL_CENTER_URL = ''
        body, status = hb.do_heartbeat()
        assert status == 503

    def test_network_failure_returns_502_no_state_change(
        self, settings, monkeypatch,
    ):
        import requests
        from licensing.models import License
        from licensing.services import heartbeat as hb

        lic_before = self._prep_active_with_key(settings)
        before_heartbeat = lic_before.last_heartbeat_at

        def _boom(*a, **kw):
            raise requests.ConnectionError('refused')
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post', _boom,
        )

        body, status = hb.do_heartbeat()
        assert status == 502
        # last_heartbeat_at NOT updated — grace must tick toward expiry.
        lic_after = License.load()
        assert lic_after.last_heartbeat_at == before_heartbeat
        assert lic_after.status == 'ACTIVE'

    def test_401_flips_to_suspended_immediately(self, settings, monkeypatch):
        from licensing.models import License
        from licensing.services import heartbeat as hb
        self._prep_active_with_key(settings)
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(401, {'message': 'unknown'}),
        )
        body, status = hb.do_heartbeat()
        assert status == 401
        lic = License.load()
        assert lic.status == 'SUSPENDED'
        # Operator-visible explanation written to the banner field.
        assert 'rejected' in lic.last_message.lower() or 'revoked' in lic.last_message.lower()

    def test_410_flips_to_suspended_too(self, settings, monkeypatch):
        from licensing.models import License
        from licensing.services import heartbeat as hb
        self._prep_active_with_key(settings)
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(410, {'message': 'revoked'}),
        )
        body, status = hb.do_heartbeat()
        assert status == 410
        assert License.load().status == 'SUSPENDED'

    def test_5xx_transient_does_not_change_state(self, settings, monkeypatch):
        from licensing.models import License
        from licensing.services import heartbeat as hb
        self._prep_active_with_key(settings)
        before_status = License.load().status
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(502, {}),
        )
        body, status = hb.do_heartbeat()
        assert status == 503
        assert License.load().status == before_status

    def test_200_active_updates_state(self, settings, monkeypatch):
        from licensing.models import License
        from licensing.services import heartbeat as hb
        from django.utils import timezone
        from datetime import timedelta

        self._prep_active_with_key(settings)
        future_iso = (timezone.now() + timedelta(days=60)).isoformat()
        now_iso = timezone.now().isoformat()
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(200, {
                'status': 'ACTIVE',
                'expires_at': future_iso,
                'server_now': now_iso,
                'next_heartbeat_in_s': 300,
                'message': 'Welcome',
                'ack_id': 'abc-123',
            }),
        )
        body, status = hb.do_heartbeat()
        assert status == 200
        lic = License.load()
        assert lic.status == 'ACTIVE'
        assert lic.last_message == 'Welcome'
        assert lic.last_heartbeat_at  # updated
        assert lic.expires_at is not None

    def test_200_suspended_flips_state_and_busts_cache(
        self, settings, monkeypatch,
    ):
        """Critical for enforcement: control center says SUSPENDED → the
        middleware must refuse the very next request, not wait 60s for
        the cache TTL."""
        from licensing.models import License
        from licensing.services import heartbeat as hb
        from django.utils import timezone

        self._prep_active_with_key(settings)
        monkeypatch.setattr(
            'licensing.services.heartbeat.requests.post',
            lambda *a, **kw: _FakeResponse(200, {
                'status': 'SUSPENDED',
                'expires_at': None,
                'server_now': timezone.now().isoformat(),
                'message': 'Subscription overdue',
                'ack_id': 'x',
            }),
        )
        # Pre-heartbeat: request would pass.
        assert _client().get('/api/admins/dashboard/today').status_code != 503

        hb.do_heartbeat()

        # Post-heartbeat: middleware must refuse immediately.
        resp = _client().get('/api/admins/dashboard/today')
        assert resp.status_code == 503
        assert resp.json()['code'] == 'license_suspended'

    def test_undecryptable_key_returns_500(self, settings, monkeypatch):
        from licensing.models import License
        from licensing.services import heartbeat as hb

        # Stash garbage in the encrypted-key field; decrypt will return
        # None and do_heartbeat should bail out with a clear status.
        settings.LICENSE_CONTROL_CENTER_URL = 'http://cc.local'
        lic = License.load()
        lic.status = License.Status.ACTIVE
        lic.key_encrypted = b'corrupted-blob'
        lic.save()

        body, status = hb.do_heartbeat()
        assert status == 500
        assert body['message'] == 'license_key_undecryptable'
