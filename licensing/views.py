"""Allowlisted endpoints — these stay open even when the license is dead.

For this first commit only `/api/licensing/status` returns useful data;
`/api/licensing/setup` and `/api/licensing/unlock` are wired up in
follow-up commits (setup wizard + perpetual unlock). They return 501
here as explicit placeholders so the URL surface is stable.
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

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
    """First-run setup wizard — wired up in a follow-up commit."""
    return JsonResponse(
        {'success': False, 'message': 'Setup wizard not yet implemented.'},
        status=501,
    )


@csrf_exempt
@require_POST
def unlock_view(request):
    """Perpetual-unlock escape hatch — wired up in a follow-up commit."""
    return JsonResponse(
        {'success': False, 'message': 'Perpetual unlock not yet implemented.'},
        status=501,
    )
