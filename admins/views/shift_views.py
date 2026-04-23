from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from admins.services.shift_service import ShiftTemplateService, ShiftService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def shift_templates(request):
    if request.method == "GET":
        result, status_code = ShiftTemplateService.list()
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    start_time = datetime.strptime(start_time_str, '%H:%M').time() if start_time_str else None
    end_time = datetime.strptime(end_time_str, '%H:%M').time() if end_time_str else None

    result, status_code = ShiftTemplateService.create(
        name=data.get('name'),
        start_time=start_time,
        end_time=end_time,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def shift_template_detail(request, template_id):
    if request.method == "GET":
        result, status_code = ShiftTemplateService.get(template_id)
        return JsonResponse(result, status=status_code)

    if request.method == "DELETE":
        result, status_code = ShiftTemplateService.delete(template_id)
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = ShiftTemplateService.update(
        template_id,
        name=data.get('name'),
        start_time=data.get('start_time'),
        end_time=data.get('end_time'),
        is_active=data.get('is_active'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@admin_required
def shifts(request):
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 20))
    user_id = request.GET.get('user_id')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    result, status_code = ShiftService.list(
        page=page,
        per_page=per_page,
        user_id=user_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@admin_required
def shift_detail(request, shift_id):
    result, status_code = ShiftService.get(shift_id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@admin_required
def shift_start(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    user_id = data.get('user_id')
    if not user_id:
        return JsonResponse(
            {"success": False, "message": "user_id is required"},
            status=400,
        )

    result, status_code = ShiftService.start_shift(
        user_id=user_id,
        shift_template_id=data.get('shift_template_id'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@admin_required
def shift_end(request, shift_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = ShiftService.end_shift(
        shift_id=shift_id,
        user_id=request.user.id,
        notes=data.get('notes', ''),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@admin_required
def shift_reconcile(request, shift_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    actual_cash = data.get('actual_cash')
    if actual_cash is None:
        return JsonResponse(
            {"success": False, "message": "actual_cash is required"},
            status=400,
        )

    result, status_code = ShiftService.reconcile(
        shift_id=shift_id,
        actual_cash=actual_cash,
        notes=data.get('notes', ''),
        reconciled_by_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@admin_required
def active_shifts(request):
    result, status_code = ShiftService.get_active_shifts()
    return JsonResponse(result, status=status_code)
