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
        # Wired up in a follow-up commit; for now it just returns 501,
        # but the kill switch must NOT have refused it first.
        _unregister_license()
        resp = _client().post('/api/licensing/setup')
        assert resp.status_code == 501

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
