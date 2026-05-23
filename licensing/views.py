"""Allowlisted endpoints — these stay open even when the license is dead.

`status` returns the current license snapshot (used by the Electron
renderer to drive setup screen vs banner vs blocked screen). `setup`
exchanges an invite code for an active license via the control center.
`unlock` accepts an Ed25519-signed perpetual-unlock file from the
vendor — wired up in a follow-up commit; here it still returns 501.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from licensing.models import License
from licensing.services import heartbeat as heartbeat_svc
from licensing.services.state import get_state


@require_GET
def status_view(request):
    """Read-only license state. Always returns 200, even when blocked,
    so the Electron renderer can display a banner / route to a setup
    screen without first running into the kill switch."""
    state = get_state()
    return JsonResponse({
        'success': True,
        'data': {
            'status': state.status,
            'expires_at': state.expires_at,
            'last_heartbeat_at': state.last_heartbeat_at,
            'grace_until': state.grace_until,
            'message': state.message or None,
            'tenant': {
                'org_name': state.org_name or None,
                'email': state.email or None,
            },
            'is_blocked': state.is_blocked(),
            'reason': state.reason_code() if state.is_blocked() else None,
        },
    })


@csrf_exempt
@require_POST
def setup_view(request):
    """First-run setup wizard.

    Body: { "email": "...", "org_name": "...", "invite_code": "..." }

    Refuses unless the License row is still UNREGISTERED — once an
    install is active, re-registering is a license-key reset and should
    flow through a different (admin-only) path. The control center is
    the source of truth for whether the invite is valid; we just relay
    the result.
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        return JsonResponse(
            {'success': False, 'message': 'Invalid JSON body'}, status=400,
        )

    email = (data.get('email') or '').strip().lower()
    org_name = (data.get('org_name') or '').strip()
    invite_code = (data.get('invite_code') or '').strip()

    missing = [
        name for name, value in (
            ('email', email), ('org_name', org_name), ('invite_code', invite_code),
        ) if not value
    ]
    if missing:
        return JsonResponse(
            {'success': False, 'message': 'Missing required fields',
             'errors': {f: f'{f} is required' for f in missing}},
            status=422,
        )

    # Singleton guard: refuse if this install is already past the
    # unregistered state. The operator's reset path is "wipe the row in
    # Django admin first" — intentionally inconvenient so a misplaced
    # POST doesn't reset a live POS.
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

    body, status = heartbeat_svc.register(
        email=email, org_name=org_name, invite_code=invite_code,
    )
    return JsonResponse(body, status=status)


@csrf_exempt
@require_POST
def unlock_view(request):
    """Perpetual-unlock escape hatch — wired up in a follow-up commit."""
    return JsonResponse(
        {'success': False, 'message': 'Perpetual unlock not yet implemented.'},
        status=501,
    )
