"""Cashier-facing shift control for the till (staff-auth, own shift only).

Shifts are manual: login no longer auto-opens one. The cashier opens their own
shift here, resumes it after logout, and closes it explicitly.

POST /shifts/start    -> open MY shift (optional shift_template_id)
POST /shifts/end      -> close MY active shift (optional notes)
GET  /shifts/current  -> MY open shift, or null (so the till can resume)

Manager/admin oversight (listing, ending anyone's shift, reconcile) stays on the
existing /api/admins/shifts/* endpoints.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from base.security.auth import login_required, role_required
from admins.services.shift_service import ShiftService

STAFF_ROLES = ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER')


def _optional_body(request):
    """Lenient parse — start/end take an optional body, so an empty/blank POST
    is valid and yields {} rather than a 400."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def start_shift(request):
    result, status_code = ShiftService.start_shift(
        user_id=request.user.id,
        shift_template_id=_optional_body(request).get('shift_template_id'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def end_shift(request):
    result, status_code = ShiftService.end_active_for_user(
        user_id=request.user.id,
        notes=_optional_body(request).get('notes', ''),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def current_shift(request):
    result, status_code = ShiftService.current_for_user(request.user.id)
    return JsonResponse(result, status=status_code)
