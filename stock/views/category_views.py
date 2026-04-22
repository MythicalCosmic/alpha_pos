from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from stock.services import StockCategoryService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def categories(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        category_type = request.GET.get("type")
        parent_id = request.GET.get("parent_id")
        tree = request.GET.get("tree", "false").lower() == "true"

        if tree:
            result, status = StockCategoryService.get_tree()
        else:
            result, status = StockCategoryService.list(
                type_filter=category_type,
                parent_id=int(parent_id) if parent_id else None,
            )
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = StockCategoryService.create(**data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@admin_required
def category_detail(request, category_id):
    if request.method == "GET":
        result, status = StockCategoryService.get(category_id)
        return JsonResponse(result, status=status)

    if request.method == "DELETE":
        cascade = request.GET.get("cascade", "false").lower() == "true"
        result, status = StockCategoryService.deactivate(category_id, cascade=cascade)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = StockCategoryService.update(category_id, **data)
    return JsonResponse(result, status=status)
