from base.helpers.request import safe_page, safe_per_page
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from base.security.auth import login_required
from customers.services.product_service import CustomerProductService


@csrf_exempt
@login_required
@require_GET
def list_products(request):
    page = safe_page(request)
    per_page = safe_per_page(request, 20)
    search = request.GET.get('search')
    category_ids = request.GET.get('category_ids')
    order_by = request.GET.get('order_by', '-created_at')
    # Top-selling first is the default; pass popular=false to disable.
    popular = request.GET.get('popular', 'true').lower() not in ('false', '0', 'no')

    result, status_code = CustomerProductService.get_all_products(
        page=page,
        per_page=per_page,
        search=search,
        category_ids=category_ids,
        order_by=order_by,
        popular=popular,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@login_required
@require_GET
def products_by_category(request, category_id):
    result, status_code = CustomerProductService.get_products_by_category(category_id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@login_required
@require_GET
def get_product(request, product_id):
    result, status_code = CustomerProductService.get_product_by_id(product_id)
    return JsonResponse(result, status=status_code)
