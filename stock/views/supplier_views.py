from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from stock.services import SupplierService, SupplierStockItemService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def suppliers(request):
    if request.method == "GET":
        result, status_code = SupplierService.list(
            page=int(request.GET.get("page", 1)),
            per_page=int(request.GET.get("per_page", 20)),
            search=request.GET.get("search"),
            active_only=request.GET.get("active_only", "true").lower() == "true",
        )
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = SupplierService.create(**data)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def supplier_detail(request, supplier_id):
    if request.method == "GET":
        result, status_code = SupplierService.get(supplier_id)
        return JsonResponse(result, status=status_code)

    if request.method == "DELETE":
        result, status_code = SupplierService.deactivate(supplier_id)
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = SupplierService.update(supplier_id, **data)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def supplier_items(request, supplier_id):
    if request.method == "GET":
        result, status_code = SupplierService.get(supplier_id, include_items=True, include_stats=False)
        return JsonResponse(result, status=status_code)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status_code = SupplierStockItemService.add_item(supplier_id=supplier_id, **data)
    return JsonResponse(result, status=status_code)
