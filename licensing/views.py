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
    """Accept a vendor-signed perpetual-unlock file.

    Body: { "unlock_file": "<base64 of JSON blob>" }

    On a valid signature the License row is flipped to PERPETUAL_UNLOCK
    and the heartbeat daemon stops trying to phone home. This is meant
    to be used only when the vendor has shut down and published the
    unlock file — see `licensing/services/unlock.py` for the threat
    model.
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, TypeError):
        return JsonResponse(
            {'success': False, 'message': 'Invalid JSON body'}, status=400,
        )

    unlock_file = (data.get('unlock_file') or '').strip()
    if not unlock_file:
        return JsonResponse(
            {'success': False, 'message': 'unlock_file is required'},
            status=422,
        )

    from licensing.services.unlock import verify_unlock_file
    is_valid, reason = verify_unlock_file(unlock_file)

    if not is_valid:
        # Log the rejection — repeated rejections might indicate someone
        # is brute-forcing signatures, though Ed25519's 256-bit security
        # makes that infeasible. Useful for support.
        from licensing.models import LicenseEvent
        LicenseEvent.objects.create(
            action=LicenseEvent.Action.UNLOCK_REJECTED,
            detail={'reason': reason},
        )
        # Map structured reasons to operator-friendly messages without
        # leaking enough to help a forger (e.g. don't echo back the
        # parsed payload string).
        message = {
            'vendor_pubkey_not_configured': (
                'This install was built without a vendor public key, '
                'so perpetual unlock cannot be verified.'
            ),
            'unlock_file_required': 'unlock_file is required.',
            'unlock_file_not_base64': 'Unlock file is not valid base64.',
            'unlock_file_not_json': 'Unlock file does not contain JSON.',
            'unlock_file_not_object': 'Unlock file JSON must be an object.',
            'payload_string_mismatch': (
                'Unlock file payload does not match the expected protocol '
                'version. Upgrade alpha_pos or obtain a v1 file.'
            ),
            'signed_at_missing': 'Unlock file is missing signed_at.',
            'signature_missing': 'Unlock file is missing signature.',
            'signature_not_hex': 'Unlock file signature is not valid hex.',
            'signature_invalid': (
                'Unlock file signature does not verify against the vendor '
                'public key embedded in this build.'
            ),
        }.get(reason, 'Unlock file could not be verified.')
        status = 503 if reason == 'vendor_pubkey_not_configured' else 422
        return JsonResponse(
            {'success': False, 'code': reason, 'message': message},
            status=status,
        )

    # Valid signature — flip the License row. After this point the kill
    # switch lets every request through and the heartbeat daemon's
    # next tick returns 304 (perpetual_unlock active).
    from django.db import transaction
    from django.utils import timezone
    from licensing.models import License, LicenseEvent

    with transaction.atomic():
        lic = License.objects.select_for_update().get(pk=1)
        prior_status = lic.status
        lic.status = License.Status.PERPETUAL_UNLOCK
        lic.last_message = (
            'This install is in PERPETUAL_UNLOCK mode — the vendor '
            'published a perpetual-unlock signature. The kill switch '
            'is permanently disabled until the License row is reset.'
        )
        # `reason` carries the signed_at from the file on success path.
        lic.last_server_now = timezone.now()
        lic.save()

    LicenseEvent.objects.create(
        action=LicenseEvent.Action.UNLOCK_ACCEPTED,
        detail={
            'signed_at': reason,
            'prior_status': prior_status,
        },
    )

    return JsonResponse({
        'success': True,
        'message': 'Perpetual unlock accepted. The kill switch is now disabled.',
        'license': {
            'status': lic.status,
            'unlock_signed_at': reason,
        },
    })
