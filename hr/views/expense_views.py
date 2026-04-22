from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from hr.services import ExpenseCategoryService, ExpenseService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def expense_categories(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        result, status = ExpenseCategoryService.list(page=page, per_page=per_page)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseCategoryService.create(**data, created_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def expense_category_detail(request, category_id):
    if request.method == "GET":
        result, status = ExpenseCategoryService.get(category_id)
        return JsonResponse(result, status=status)

    if request.method == "DELETE":
        result, status = ExpenseCategoryService.delete(category_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseCategoryService.update(category_id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def expenses(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        result, status = ExpenseService.list(page=page, per_page=per_page)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseService.create(**data, created_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def expense_detail(request, expense_id):
    if request.method == "GET":
        result, status = ExpenseService.get(expense_id)
        return JsonResponse(result, status=status)

    if request.method == "DELETE":
        result, status = ExpenseService.delete(expense_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseService.update(expense_id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def expense_approve(request, expense_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseService.approve(expense_id, approved_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def expense_reject(request, expense_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseService.reject(expense_id, rejected_by_id=request.user.id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def expense_pay(request, expense_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ExpenseService.pay(expense_id, paid_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def expense_stats(request):
    result, status = ExpenseService.stats()
    return JsonResponse(result, status=status)
