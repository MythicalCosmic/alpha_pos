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
from datetime import timedelta
from typing import Any, Dict, Tuple

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from licensing.models import License, LicenseEvent
from licensing.services import crypto, state as state_mod


logger = logging.getLogger(__name__)


# Heartbeat / register HTTP timeout — short enough that a hung control
# center doesn't tie up a worker, long enough for a normal round trip on
# a slow connection.
_HTTP_TIMEOUT_S = 10


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


def _client_version() -> str:
    """Short version string for the heartbeat payload. The control
    center records it per-event for support diagnostics."""
    # Lightweight: pull git SHA at runtime, falling back to 'unknown'.
    import subprocess
    try:
        sha = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        if sha:
            return f'alpha_pos@{sha}'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 'alpha_pos@unknown'


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
    status_in = payload.get('status', License.Status.ACTIVE)
    valid_statuses = {c[0] for c in License.Status.choices}
    if status_in not in valid_statuses:
        status_in = License.Status.ACTIVE

    server_now = _parse_iso(payload.get('server_now')) or timezone.now()

    lic.status = status_in
    lic.expires_at = _parse_iso(payload.get('expires_at'))
    lic.last_message = payload.get('message') or ''
    lic.last_heartbeat_at = timezone.now()
    lic.last_server_now = server_now
    lic.save()
    # save() busts both license:row and license:state caches.
    return lic


# ---------------------------------------------------------------------------
# Setup wizard helper
# ---------------------------------------------------------------------------


def register(email: str, org_name: str, invite_code: str) -> Tuple[Dict[str, Any], int]:
    """POST /api/v1/register on the control center. On success, encrypt
    and persist the returned key + flip status to ACTIVE.

    Returns (body, http_status). The caller (the setup wizard view) just
    re-emits these. The license key is NEVER returned in the body — it
    is stored encrypted server-side and never shown again.
    """
    url = _control_url('/api/v1/register')
    if not getattr(settings, 'LICENSE_CONTROL_CENTER_URL', ''):
        return ({
            'success': False,
            'message': 'LICENSE_CONTROL_CENTER_URL is not configured on this install.',
            'code': 'control_center_url_missing',
        }, 503)

    payload = {
        'email': email, 'org_name': org_name, 'invite_code': invite_code,
    }
    LicenseEvent.objects.create(
        action=LicenseEvent.Action.SETUP_ATTEMPTED,
        detail={'email': email, 'org_name': org_name, 'has_invite': bool(invite_code)},
    )

    try:
        resp = requests.post(url, json=payload, timeout=_HTTP_TIMEOUT_S)
    except requests.RequestException as exc:
        logger.exception('register: HTTP to control center failed')
        return ({
            'success': False,
            'message': f'Could not reach the control center: {exc}',
            'code': 'control_center_unreachable',
        }, 502)

    # Bubble the control center's error responses up unchanged so the
    # operator sees "invite already used" / "expired" / etc. with the
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

    with transaction.atomic():
        lic = License.objects.select_for_update().get(pk=1)
        lic.key_encrypted = crypto.encrypt_key(key)
        lic.email = email
        lic.org_name = org_name
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
        detail={'email': email, 'org_name': org_name, 'tenant_id': body.get('tenant_id')},
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
# Heartbeat — wired up in the next commit alongside the daemon.
# ---------------------------------------------------------------------------


def do_heartbeat() -> Tuple[Dict[str, Any], int]:
    """Stub. The full heartbeat loop is implemented in the next commit
    when the management command lands."""
    return ({'success': False, 'message': 'heartbeat not implemented yet'}, 501)
