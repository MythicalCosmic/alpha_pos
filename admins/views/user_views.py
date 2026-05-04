import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from base.helpers.request import parse_json_body, validate_pagination
from base.helpers.response import json_response
from base.security.permissions import admin_required, permission_required
from admins.services.user_service import AdminUserService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def users(request):
    if request.method == "GET":
        page, per_page = validate_pagination(request)
        search = request.GET.get('search', '').strip()
        status = request.GET.get('status')
        role = request.GET.get('role')

        result, status_code = AdminUserService.list_users(
            page=page, per_page=per_page, search=search or None,
            status=status, role=role,
        )
        return JsonResponse(result, status=status_code)

    # POST — create user
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = AdminUserService.create_user(
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', ''),
        role=data.get('role', 'CASHIER'),
        password=data.get('password'),
        email=data.get('email'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
@admin_required
def user_detail(request, user_id):
    if request.method == "GET":
        result, status_code = AdminUserService.get_user(user_id)
        return JsonResponse(result, status=status_code)

    if request.method in ("PUT", "PATCH"):
        data, error = parse_json_body(request)
        if error:
            return json_response(error)

        result, status_code = AdminUserService.update_user(user_id, **data)
        return JsonResponse(result, status=status_code)

    if request.method == "DELETE":
        result, status_code = AdminUserService.delete_user(user_id)
        return JsonResponse(result, status=status_code)
