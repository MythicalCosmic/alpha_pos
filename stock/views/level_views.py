from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from base.helpers.request import parse_json_body, safe_page, safe_per_page
from base.helpers.response import json_response
from base.security.permissions import admin_required
from stock.services.level_service import StockLevelService, StockTransactionService


@csrf_exempt
@require_GET
@admin_required
def stock_levels(request):
    result, status = StockLevelService.get_all(
        page=safe_page(request),
        per_page=safe_per_page(request, 50),
        location_id=int(request.GET.get("location_id")) if request.GET.get("location_id") else None,
        category_id=int(request.GET.get("category_id")) if request.GET.get("category_id") else None,
        item_type=request.GET.get("item_type"),
        low_stock_only=request.GET.get("low_stock_only", "").lower() == "true",
        search=request.GET.get("search"),
    )
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def stock_level_item(request, item_id):
    result, status = StockLevelService.get_for_item(item_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def stock_level_location(request, location_id):
    result, status = StockLevelService.get_for_location(location_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def stock_adjust(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    result, status = StockLevelService.adjust(**data, user_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def stock_reserve(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    result, status = StockLevelService.reserve(**data, user_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def stock_release_reservation(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    result, status = StockLevelService.release_reservation(**data, user_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def low_stock(request):
    location_id = int(request.GET.get("location_id")) if request.GET.get("location_id") else None
    result, status = StockLevelService.get_low_stock_items(location_id=location_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def transactions(request):
    date_from = None
    date_to = None
    if request.GET.get("date_from"):
        date_from = datetime.fromisoformat(request.GET["date_from"]).date()
    if request.GET.get("date_to"):
        date_to = datetime.fromisoformat(request.GET["date_to"]).date()

    result, status = StockTransactionService.list(
        page=safe_page(request),
        per_page=safe_per_page(request, 50),
        stock_item_id=int(request.GET.get("stock_item_id")) if request.GET.get("stock_item_id") else None,
        location_id=int(request.GET.get("location_id")) if request.GET.get("location_id") else None,
        movement_type=request.GET.get("type"),
        date_from=date_from,
        date_to=date_to,
    )
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@admin_required
def transaction_history(request, item_id):
    days = int(request.GET.get("days", 30))
    result, status = StockTransactionService.get_item_history(item_id, days)
    return JsonResponse(result, status=status)
