"""Operational analytics endpoints."""
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from admins.services.analytics_service import menu_engineering, shift_performance
from base.models import Shift
from base.security.permissions import admin_required


@require_GET
@admin_required
def shift_perf_view(request, shift_id):
    try:
        shift = Shift.objects.select_related('user').get(
            id=shift_id, is_deleted=False,
        )
    except Shift.DoesNotExist:
        return JsonResponse(
            {'success': False, 'message': 'Shift not found'}, status=404,
        )
    return JsonResponse({'success': True, 'data': shift_performance(shift)})


@require_GET
@admin_required
def menu_engineering_view(request):
    df_str = request.GET.get('from')
    dt_str = request.GET.get('to')
    df = parse_date(df_str) if df_str else None
    dt = parse_date(dt_str) if dt_str else None
    if not df or not dt:
        return JsonResponse(
            {'success': False, 'message': 'from and to (YYYY-MM-DD) are required'},
            status=422,
        )
    if df > dt:
        return JsonResponse(
            {'success': False, 'message': 'from must be on or before to'},
            status=422,
        )

    cogs_str = request.GET.get('cogs_fraction')
    cogs = None
    if cogs_str:
        try:
            cogs = Decimal(cogs_str)
        except (InvalidOperation, TypeError):
            return JsonResponse(
                {'success': False, 'message': 'cogs_fraction must be a decimal'},
                status=422,
            )
        if cogs <= 0 or cogs >= 1:
            return JsonResponse(
                {'success': False, 'message': 'cogs_fraction must be between 0 and 1 (exclusive)'},
                status=422,
            )

    kwargs = {'cogs_fraction': cogs} if cogs is not None else {}
    return JsonResponse(
        {'success': True, 'data': menu_engineering(df, dt, **kwargs)},
    )
