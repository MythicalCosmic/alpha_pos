from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from hr.services import DepartmentService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def departments(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        result, status = DepartmentService.list(page=page, per_page=per_page)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = DepartmentService.create(**data, created_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def department_detail(request, department_id):
    if request.method == "GET":
        result, status = DepartmentService.get(department_id)
        return JsonResponse(result, status=status)

    if request.method == "DELETE":
        result, status = DepartmentService.delete(department_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = DepartmentService.update(department_id, **data)
    return JsonResponse(result, status=status)
