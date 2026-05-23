from base.helpers.request import safe_page, safe_per_page
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from base.security.auth import login_required
from customers.services.category_service import CustomerCategoryService


@csrf_exempt
@login_required
@require_GET
def list_categories(request):
    page = safe_page(request)
    per_page = safe_per_page(request, 20)
    search = request.GET.get('search')
    status = request.GET.get('status')
    order_by = request.GET.get('order_by', 'sort_order')

    result, status_code = CustomerCategoryService.get_all_categories(
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        order_by=order_by,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@login_required
@require_GET
def active_categories(request):
    result, status_code = CustomerCategoryService.get_active_categories()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@login_required
@require_GET
def get_category(request, category_id):
    result, status_code = CustomerCategoryService.get_category_by_id(category_id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@login_required
@require_GET
def get_category_by_slug(request, slug):
    result, status_code = CustomerCategoryService.get_category_by_slug(slug)
    return JsonResponse(result, status=status_code)
