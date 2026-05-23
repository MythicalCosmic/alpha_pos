from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body, safe_page, safe_per_page
from base.helpers.response import json_response
from base.security.permissions import admin_required
from stock.services import StockBatchService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def batches(request):
    if request.method == "GET":
        expiring_within_days = None
        if request.GET.get("expiring_within_days"):
            expiring_within_days = int(request.GET["expiring_within_days"])

        result, status_code = StockBatchService.list(
            page=safe_page(request),
            per_page=safe_per_page(request, 50),
            stock_item_id=int(request.GET.get("stock_item_id")) if request.GET.get("stock_item_id") else None,
            location_id=int(request.GET.get("location_id")) if request.GET.get("location_id") else None,
            status=request.GET.get("status"),
            has_stock_only=request.GET.get("has_stock_only", "true").lower() != "false",
            expired_only=request.GET.get("expired_only", "").lower() == "true",
            expiring_within_days=expiring_within_days,
        )
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = StockBatchService.create(**data)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["GET", "PUT"])
@admin_required
def batch_detail(request, batch_id):
    if request.method == "GET":
        result, status_code = StockBatchService.get(batch_id)
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = StockBatchService.update(batch_id, **data)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@admin_required
def batch_consume(request, batch_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = StockBatchService.consume(
        batch_id=batch_id,
        quantity=data["quantity"],
        user_id=request.user.id,
        notes=data.get("notes"),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@admin_required
def batch_auto_consume(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = StockBatchService.auto_consume(
        stock_item_id=data["stock_item_id"],
        location_id=data["location_id"],
        quantity=data["quantity"],
        user_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@admin_required
def expiring_batches(request):
    days = int(request.GET.get("days", 7))
    result, status_code = StockBatchService.get_expiring_batches(days)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@admin_required
def expired_batches(request):
    result, status_code = StockBatchService.get_expired_batches()
    return JsonResponse(result, status=status_code)
