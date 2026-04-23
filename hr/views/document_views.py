from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from hr.services import DocumentService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def documents(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        employee_id = request.GET.get("employee_id")
        document_type = request.GET.get("document_type")
        result, status_code = DocumentService.list(
            page=page, per_page=per_page, employee_id=employee_id, document_type=document_type
        )
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = DocumentService.create(**data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def document_detail(request, doc_id):
    if request.method == "GET":
        result, status = DocumentService.get(doc_id)
        return JsonResponse(result, status=status)

    if request.method == "DELETE":
        result, status = DocumentService.delete(doc_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = DocumentService.update(doc_id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def document_verify(request, doc_id):
    result, status = DocumentService.verify(doc_id, verified_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def documents_expiring(request):
    days = int(request.GET.get("days", 30))
    result, status = DocumentService.get_expiring(days=days)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def documents_by_employee(request, employee_id):
    result, status = DocumentService.get_by_employee(employee_id)
    return JsonResponse(result, status=status)
