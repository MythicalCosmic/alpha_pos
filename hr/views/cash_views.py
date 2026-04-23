from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from hr.services import CashTransactionService


@csrf_exempt
@require_GET
@admin_required
def cash_transactions(request):
    page = int(request.GET.get("page", 1))
    per_page = int(request.GET.get("per_page", 20))
    result, status = CashTransactionService.list(page=page, per_page=per_page)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def cash_transaction_detail(request, transaction_id):
    result, status = CashTransactionService.get(transaction_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def cash_deposit(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = CashTransactionService.deposit(**data, performed_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def cash_withdraw(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = CashTransactionService.withdraw(**data, performed_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def cash_balance(request):
    result, status = CashTransactionService.get_balance_summary()
    return JsonResponse(result, status=status)
