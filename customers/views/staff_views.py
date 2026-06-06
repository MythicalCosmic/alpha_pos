from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from base.security.rate_limit import rate_limit
from customers.services.staff_service import StaffService


@csrf_exempt
@rate_limit('staff_list', 30, 60)
@require_GET
def list_cashiers(request):
    # Public on purpose: this feeds the monoblock login screen, which is
    # shown before any cashier has authenticated. No session required.
    result, status_code = StaffService.list_cashiers()
    return JsonResponse(result, status=status_code)
