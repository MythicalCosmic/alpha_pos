"""Payment-method catalog for the cashier payment screen.

The frontend fetches this once after login and caches it per-PC, rendering one
button per active method with its label, inline SVG icon and accent color — so
methods/branding change from the backend without a frontend release.
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from base.models import PaymentMethodConfig
from base.security.auth import login_required, role_required

STAFF_ROLES = ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER')


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def payment_methods(request):
    rows = PaymentMethodConfig.objects.filter(is_active=True).order_by('sort_order', 'code')
    return JsonResponse({
        'success': True,
        'data': {
            'methods': [
                {
                    'code': r.code,
                    'label': r.label,
                    'icon': r.icon,
                    'color': r.color,
                    'sort_order': r.sort_order,
                    'is_active': r.is_active,
                }
                for r in rows
            ],
        },
    })
