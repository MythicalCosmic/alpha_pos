"""Allowlisted endpoints — these stay open even when the license is dead.

`status` returns the current license snapshot (used by the renderer to
drive setup screen vs banner vs blocked screen). `setup` exchanges an
email for an active license via the control center.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from base.security.rate_limit import rate_limit, rate_limit_by
from licensing.models import License
from licensing.services import heartbeat as heartbeat_svc
from licensing.services.state import get_state


@require_GET
def status_view(request):
    """Read-only license state. Always returns 200, even when blocked,
    so the Electron renderer can display a banner / route to a setup
    screen without first running into the kill switch.

    This endpoint is intentionally unauthenticated (the renderer hits it
    before login). Tenant identity (org_name / email) is therefore *not*
    returned here — that's available to authenticated callers via the
    existing admin endpoints. Returning it here would leak operator
    identity to any LAN attacker who can TCP to the host.
    """
    state = get_state()
    return JsonResponse({
        'success': True,
        'data': {
            'status': state.status,
            'expires_at': state.expires_at,
            'last_heartbeat_at': state.last_heartbeat_at,
            'grace_until': state.grace_until,
            'message': state.message or None,
            'is_blocked': state.is_blocked(),
            'reason': state.reason_code() if state.is_blocked() else None,
            # Prepaid-billing snapshot for the renderer: show remaining
            # balance / days and raise a "top up soon" banner when `warn`
            # is set, before the kill switch ever fires.
            'balance': state.balance,
            'days_remaining': state.days_remaining,
            'warn': state.warn,
        },
    })


def _setup_email_prefix(request):
    """Per-email throttle key. We hash the address rather than use it raw so
    the cache key isn't itself a PII leak."""
    try:
        import hashlib
        body = json.loads(request.body) if request.body else {}
        email = ((body.get('email') if isinstance(body, dict) else '') or '').strip().lower()
        if not email:
            return None
        return hashlib.sha256(email.encode('utf-8')).hexdigest()[:16]
    except (ValueError, TypeError):
        return None


@csrf_exempt
@require_POST
# Throttle so a LAN-side attacker can't spray email addresses against the
# control center via this proxy. IP + email-prefix gives two axes: one
# attacker IP can try 5 / 5min total, and any single email gets 3 / 5min
# across all sources.
@rate_limit('license_setup', 5, 300)
@rate_limit_by('license_setup_email', 3, 300, _setup_email_prefix)
def setup_view(request):
    """First-run setup wizard.

    Body: { "email": "..." }

    Email is the only thing the operator types. The control center self-serves
    a tenant against that address (no invite code, no org name). The org name
    can be filled in later via an admin endpoint.

    Refuses unless the License row is still UNREGISTERED — once an install is
    active, re-registering is a license-key reset and should flow through a
    different (admin-only) path.
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        return JsonResponse(
            {'success': False, 'message': 'Invalid JSON body'}, status=400,
        )

    email = (data.get('email') or '').strip().lower()
    if not email:
        return JsonResponse(
            {'success': False, 'message': 'Missing required fields',
             'errors': {'email': 'email is required'}},
            status=422,
        )

    # Singleton guard: refuse if this install is already past the
    # unregistered state. The operator's reset path is "wipe the row in
    # Django admin first" — intentionally inconvenient so a misplaced
    # POST doesn't reset a live POS. register() re-checks this under a
    # row lock to close the TOCTOU on two concurrent setups.
    current = License.load()
    if current.status != License.Status.UNREGISTERED:
        return JsonResponse(
            {'success': False,
             'message': f'This install is already in state {current.status}. '
                        'Reset the License row before re-running setup.',
             'code': 'already_registered',
             'status': current.status},
            status=409,
        )

    body, status = heartbeat_svc.register(email=email)
    return JsonResponse(body, status=status)


