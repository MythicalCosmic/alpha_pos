"""Client-side talker to the pos_control_center.

This module owns the HTTP calls to /api/v1/register and /api/v1/heartbeat.
The heartbeat daemon (management command) imports `do_heartbeat`; the
setup wizard view imports `register`. Both return ServiceResponse-like
tuples (data, http_status) so views and the daemon stay thin.

Network failures are returned as errors, never raised — the caller
should be free to decide whether to surface them or queue a retry.
"""
import logging
import platform
import socket
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Tuple

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from licensing.models import License, LicenseEvent
from licensing.services import crypto


logger = logging.getLogger(__name__)


def _http_timeout_s() -> int:
    """Heartbeat / register HTTP timeout — short enough that a hung control
    center doesn't tie up a worker, long enough for a normal round trip on
    a slow connection. Driven by LICENSE_HTTP_TIMEOUT_S so deployments on
    flaky links can raise it."""
    return getattr(settings, 'LICENSE_HTTP_TIMEOUT_S', 10)


def _fingerprint() -> str:
    """sha256 of (hostname + machine-id). Stable across restarts of the
    same container; changes if the install is cloned to a new host. Used
    by the control center to flag duplicate installs (don't auto-block —
    surface only)."""
    import hashlib
    parts = [socket.gethostname()]
    try:
        with open('/etc/machine-id') as f:
            parts.append(f.read().strip())
    except OSError:
        parts.append(platform.node())
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


# Cached at module load: every heartbeat tick used to fork `git rev-parse`,
# which is wasted work in a Docker image without .git anyway. Resolved
# exactly once per process, falling back gracefully when git is absent.
_CLIENT_VERSION_CACHED: Optional[str] = None


def _client_version() -> str:
    """Short version string for the heartbeat payload. The control
    center records it per-event for support diagnostics."""
    global _CLIENT_VERSION_CACHED
    if _CLIENT_VERSION_CACHED is not None:
        return _CLIENT_VERSION_CACHED
    import subprocess
    try:
        sha = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        _CLIENT_VERSION_CACHED = f'alpha_pos@{sha}' if sha else 'alpha_pos@unknown'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _CLIENT_VERSION_CACHED = 'alpha_pos@unknown'
    return _CLIENT_VERSION_CACHED


def _control_url(path: str) -> str:
    base = (getattr(settings, 'LICENSE_CONTROL_CENTER_URL', '') or '').rstrip('/')
    return f'{base}/{path.lstrip("/")}'


def _parse_iso(value):
    if not value:
        return None
    if hasattr(value, 'isoformat'):
        return value
    return parse_datetime(value)


def _apply_heartbeat_response(lic: License, payload: Dict[str, Any]) -> License:
    """Mutate the License singleton from a /heartbeat (or /register)
    response. Writes through the cache so the middleware sees the new
    state on the next request."""
    valid_statuses = {c[0] for c in License.Status.choices}
    status_in = payload.get('status', License.Status.ACTIVE)
    if status_in not in valid_statuses:
        # Fail CLOSED on an unknown status: preserve whatever the License row
        # already held rather than coercing to ACTIVE. A bug or a malicious
        # MITM that drops in an unknown string must not silently revive a
        # SUSPENDED / EXPIRED install.
        logger.warning(
            'heartbeat: unknown status %r in response; preserving current %r',
            status_in, lic.status,
        )
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.HEARTBEAT_FAILED,
            detail={'kind': 'unknown_status', 'received': str(status_in)[:40]},
        )
        status_in = lic.status

    server_now = _parse_iso(payload.get('server_now')) or timezone.now()

    # Replay protection: refuse responses whose server clock is older than the
    # newest one already applied. Without this, a captured prior 200 could be
    # replayed to refresh last_heartbeat_at and extend the offline-grace window
    # indefinitely. server_now is monotonic for legitimate responses. Comparison
    # errors (naive/aware mismatch) fail toward applying — no worse than before.
    try:
        is_stale = bool(lic.last_server_now) and server_now < lic.last_server_now
    except TypeError:
        is_stale = False
    if is_stale:
        logger.warning(
            'heartbeat: ignoring stale/replayed response (server_now %s < last %s)',
            server_now, lic.last_server_now,
        )
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.HEARTBEAT_FAILED,
            detail={'kind': 'stale_server_now'},
        )
        return lic

    lic.status = status_in
    lic.expires_at = _parse_iso(payload.get('expires_at'))
    lic.last_message = payload.get('message') or ''
    lic.last_heartbeat_at = timezone.now()
    lic.last_server_now = server_now

    # Prepaid-billing snapshot (display-only). The control center sends
    # `balance` as a string, `days_remaining` as an int (or null), and `warn`
    # as a bool. Older control centers omit these — leave them None/False.
    balance_in = payload.get('balance')
    try:
        lic.balance = Decimal(str(balance_in)) if balance_in not in (None, '') else None
    except (InvalidOperation, ValueError):
        lic.balance = None
    days_in = payload.get('days_remaining')
    # bool is a subclass of int in Python — exclude it so a stray True/False
    # can't be coerced into a day count.
    lic.days_remaining = days_in if (isinstance(days_in, int) and not isinstance(days_in, bool)) else None
    lic.warn = bool(payload.get('warn', False))

    lic.save()
    # save() busts both license:row and license:state caches.
    return lic


# ---------------------------------------------------------------------------
# Setup wizard helper
# ---------------------------------------------------------------------------


def register(email: str) -> Tuple[Dict[str, Any], int]:
    """POST /api/v1/register on the control center. On success, encrypt
    and persist the returned key + flip status to ACTIVE.

    Email is the only thing the operator types. The control center self-serves
    a tenant for that address (no invite code, no org name — the renderer can
    let the operator edit org_name later via an admin endpoint). The bearer
    key returned by the server is encrypted at rest and never echoed back to
    the caller.

    Returns (body, http_status). The caller (the setup wizard view) just
    re-emits these.
    """
    url = _control_url('/api/v1/register')
    if not getattr(settings, 'LICENSE_CONTROL_CENTER_URL', ''):
        return ({
            'success': False,
            'message': 'LICENSE_CONTROL_CENTER_URL is not configured on this install.',
            'code': 'control_center_url_missing',
        }, 503)

    payload = {'email': email}
    LicenseEvent.objects.create(
        action=LicenseEvent.Action.SETUP_ATTEMPTED,
        detail={'email': email},
    )

    try:
        resp = requests.post(url, json=payload, timeout=_http_timeout_s())
    except requests.RequestException as exc:
        logger.exception('register: HTTP to control center failed')
        return ({
            'success': False,
            'message': f'Could not reach the control center: {exc}',
            'code': 'control_center_unreachable',
        }, 502)

    # Bubble the control center's error responses up unchanged so the
    # operator sees "email already used" / "invalid" / etc. with the
    # same status code the control center returned.
    if resp.status_code != 201:
        try:
            body = resp.json()
        except ValueError:
            body = {'success': False, 'message': resp.text[:500]}
        # Normalize the shape so the wizard caller always gets success+message.
        body.setdefault('success', False)
        body.setdefault('message', f'Control center returned {resp.status_code}')
        return body, resp.status_code

    body = resp.json()
    key = body.get('key') or ''
    if not key:
        return ({
            'success': False,
            'message': 'Control center returned a malformed response (no key).',
            'code': 'control_center_response_invalid',
        }, 502)

    # TOCTOU close: recheck the singleton status INSIDE the row lock. The
    # view-level check happens outside any transaction, so two parallel setup
    # POSTs (different IPs, escaping the per-IP rate limit) could both pass
    # it; without this guard the second would clobber the first's encrypted
    # key with its own. select_for_update + the recheck makes the second one
    # error out cleanly.
    with transaction.atomic():
        lic = License.objects.select_for_update().get(pk=1)
        if lic.status != License.Status.UNREGISTERED:
            return ({
                'success': False,
                'code': 'already_registered',
                'message': f'This install is already in state {lic.status}.',
                'status': lic.status,
            }, 409)
        lic.key_encrypted = crypto.encrypt_key(key)
        lic.email = email
        # org_name is set later via the admin/owner-profile endpoint once
        # signup is done. Keep it empty (model default) at registration.
        lic.fingerprint = _fingerprint()
        lic.registered_at = timezone.now()
        # Treat the /register response shape as a heartbeat response.
        # _apply_heartbeat_response handles status / expires_at / server_now.
        _apply_heartbeat_response(lic, {
            'status': License.Status.ACTIVE,
            'expires_at': body.get('expires_at'),
            'server_now': body.get('issued_at') or timezone.now().isoformat(),
            'message': '',
        })

    LicenseEvent.objects.create(
        action=LicenseEvent.Action.SETUP_SUCCEEDED,
        detail={'email': email, 'tenant_id': body.get('tenant_id')},
    )

    return ({
        'success': True,
        'message': 'License activated.',
        'license': _sanitized_license(lic),
    }, 201)


def _sanitized_license(lic: License) -> Dict[str, Any]:
    """Public-safe snapshot of the License — never includes the key."""
    return {
        'status': lic.status,
        'org_name': lic.org_name,
        'email': lic.email,
        'expires_at': lic.expires_at.isoformat() if lic.expires_at else None,
        'registered_at': lic.registered_at.isoformat() if lic.registered_at else None,
        'last_heartbeat_at': (
            lic.last_heartbeat_at.isoformat() if lic.last_heartbeat_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Heartbeat — periodic phone-home to confirm the license is still valid.
# ---------------------------------------------------------------------------


def do_heartbeat() -> Tuple[Dict[str, Any], int]:
    """Send one heartbeat to the control center. Returns (body, status)
    where status mirrors HTTP semantics:
      200  — success, License row updated, status applied.
      304  — no-op (UNREGISTERED / PERPETUAL_UNLOCK — nothing to phone
             home about; the daemon should not count this as failure).
      401  — control center rejected our key (revoked / unknown). Local
             License is flipped to SUSPENDED with an explanatory message
             so the kill switch fires immediately, before grace.
      410  — same as 401 but explicitly "revoked"; same local effect.
      502  — network failure; License unchanged (grace ticks).
      503  — control center 5xx / transient; License unchanged.
    """
    if not getattr(settings, 'LICENSE_CONTROL_CENTER_URL', ''):
        return ({
            'success': False, 'message': 'control_center_url not configured',
        }, 503)

    lic = License.load()
    if lic.status == License.Status.UNREGISTERED:
        return ({'success': False, 'message': 'license unregistered'}, 304)
    if lic.status == License.Status.PERPETUAL_UNLOCK:
        # Vendor disappeared, escape hatch active — there is no control
        # center to call. Daemon caller should treat 304 as "nothing to
        # do" and not reschedule failure backoff.
        return ({'success': False, 'message': 'perpetual_unlock active'}, 304)

    cleartext = crypto.decrypt_key(lic.key_encrypted)
    if not cleartext:
        # LICENSE_FERNET_KEY rotated, or the stored blob is corrupt. The
        # operator must re-run setup. Log loudly; don't crash the daemon.
        logger.error(
            'heartbeat: cannot decrypt stored license key — operator must '
            're-run setup wizard',
        )
        return ({
            'success': False, 'message': 'license_key_undecryptable',
        }, 500)

    payload = {
        'client_version': _client_version(),
        'branch_id': getattr(settings, 'BRANCH_ID', 'main'),
        'fingerprint': _fingerprint(),
        'sent_at': timezone.now().isoformat(),
        'metrics': _collect_metrics(),
    }
    headers = {'Authorization': f'Bearer {cleartext}'}

    try:
        resp = requests.post(
            _control_url('/api/v1/heartbeat'),
            json=payload, headers=headers, timeout=_http_timeout_s(),
        )
    except requests.RequestException as exc:
        # Network failure: do NOT update last_heartbeat_at so grace
        # continues to count down. Logged at WARNING — common in normal
        # operations (brief internet outage); INFO would be noisy.
        logger.warning('heartbeat: network failure: %s', exc)
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.HEARTBEAT_FAILED,
            detail={'kind': 'network', 'error': str(exc)[:200]},
        )
        return ({'success': False, 'message': str(exc)}, 502)

    if resp.status_code in (401, 410):
        # Control center says our key is bad. Flip local status so the
        # kill switch fires immediately rather than waiting for the
        # full offline-grace window. The exact reason (REVOKED vs bad
        # key) doesn't matter to enforcement — both block.
        #
        # Do NOT bump last_heartbeat_at / last_server_now here: a rejected
        # heartbeat is not a successful one. Leaving the timestamps alone
        # keeps the grace clock honest in case status enforcement ever gets
        # softened.
        with transaction.atomic():
            lic = License.objects.select_for_update().get(pk=1)
            lic.status = License.Status.SUSPENDED
            lic.last_message = (
                'Control center rejected this license key. Contact your '
                'POS vendor — the key may have been revoked.'
            )
            lic.save()
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.STATUS_CHANGED,
            detail={'from': 'ACTIVE', 'to': 'SUSPENDED',
                    'reason': f'control_center_status_{resp.status_code}'},
        )
        return ({'success': False, 'message': 'rejected by control center',
                 'status_code': resp.status_code}, resp.status_code)

    if resp.status_code >= 500:
        # 5xx is transient; don't update last_heartbeat_at, let grace tick.
        logger.warning('heartbeat: control center 5xx %s', resp.status_code)
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.HEARTBEAT_FAILED,
            detail={'kind': 'http_5xx', 'status_code': resp.status_code},
        )
        return ({'success': False, 'message': 'control center error',
                 'status_code': resp.status_code}, 503)

    if resp.status_code != 200:
        # Unexpected status (e.g. 4xx other than 401/410). Surface but
        # don't change local state. This catches contract drift.
        logger.warning('heartbeat: unexpected status %s', resp.status_code)
        return ({'success': False, 'message': 'unexpected status',
                 'status_code': resp.status_code}, resp.status_code)

    try:
        body = resp.json()
    except ValueError:
        return ({'success': False, 'message': 'invalid response body'}, 502)

    # Success path: apply the response to the License row + bust cache.
    # The cache bust here is what makes the suspend → enforce gap as
    # short as one heartbeat (5 min default) rather than the 60s cache
    # TTL window.
    with transaction.atomic():
        lic = License.objects.select_for_update().get(pk=1)
        prior_status = lic.status
        _apply_heartbeat_response(lic, body)
        if lic.status != prior_status:
            LicenseEvent.objects.create(
                action=LicenseEvent.Action.STATUS_CHANGED,
                detail={'from': prior_status, 'to': lic.status,
                        'ack_id': body.get('ack_id')},
            )

    LicenseEvent.objects.create(
        action=LicenseEvent.Action.HEARTBEAT_OK,
        detail={'status': lic.status, 'ack_id': body.get('ack_id')},
    )
    return body, 200


def _collect_metrics() -> Dict[str, Any]:
    """Tiny diagnostic payload for the control-center support view.
    Bounded on purpose — never include PII or order content."""
    # We intentionally don't import models at module load to keep startup
    # cheap. Import inside the function so a stock daemon process doesn't
    # eagerly initialise base.models.
    from django.db import DatabaseError
    metrics = {}
    try:
        from base.models import Order
        from django.utils import timezone as tz
        from datetime import timedelta
        cutoff = tz.now() - timedelta(hours=24)
        metrics['orders_24h'] = Order.objects.filter(
            created_at__gte=cutoff, is_deleted=False,
        ).count()
    except (ImportError, DatabaseError):
        # Schema may not exist (fresh install, mid-migration) or base hasn't
        # loaded yet — skip rather than crash the heartbeat. Anything wider
        # would hide real bugs in the metrics path.
        logger.debug('heartbeat: metrics collection skipped', exc_info=True)
    return metrics
