from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from base.helpers.request import parse_json_body
from base.helpers.response import json_response, ServiceResponse
from base.security.permissions import admin_required
from stock.services.ai_assistant_service import AIStockAssistant


@csrf_exempt
@require_POST
@admin_required
def ai_query(request):
    # The assistant calls Gemini. Without a key the SDK raises deep in the
    # request, surfacing as a 500 with no actionable message. Return 503 so
    # the client can hide the feature instead of showing a generic failure.
    if not getattr(settings, 'GEMINI_API_KEY', ''):
        return JsonResponse({
            'success': False,
            'message': 'AI assistant is not configured (GEMINI_API_KEY missing).',
        }, status=503)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    query = (data.get('query') or '').strip()
    if not query:
        return json_response(ServiceResponse.validation_error(
            errors={'query': 'Query is required'},
        ))

    result = AIStockAssistant.process_query(
        query=query,
        context=data.get('context'),
        user_id=request.user.id,
        location_id=data.get('location_id'),
    )
    return JsonResponse(result)


@csrf_exempt
@require_GET
@admin_required
def ai_suggestions(request):
    from django.db.models import F
    from django.utils import timezone
    from datetime import timedelta
    from stock.models import StockLevel, StockBatch, PurchaseOrder

    suggestions = []

    low_stock_count = StockLevel.objects.filter(
        quantity__lte=F('stock_item__reorder_point'),
        is_deleted=False,
    ).count()
    if low_stock_count > 0:
        suggestions.append({
            'query': 'Show low stock items',
            'reason': f'{low_stock_count} items below reorder level',
            'priority': 'high',
        })

    expiring_count = StockBatch.objects.filter(
        expiry_date__lte=timezone.now().date() + timedelta(days=7),
        expiry_date__gt=timezone.now().date(),
        current_quantity__gt=0,
        is_deleted=False,
    ).count()
    if expiring_count > 0:
        suggestions.append({
            'query': "What's expiring this week?",
            'reason': f'{expiring_count} batches expiring soon',
            'priority': 'high',
        })

    pending_count = PurchaseOrder.objects.filter(
        status__in=['SENT', 'CONFIRMED', 'PARTIAL'],
        is_deleted=False,
    ).count()
    if pending_count > 0:
        suggestions.append({
            'query': 'Show pending deliveries',
            'reason': f'{pending_count} orders waiting',
            'priority': 'medium',
        })

    suggestions.extend([
        {'query': 'Stock overview', 'reason': 'See inventory summary', 'priority': 'low'},
        {'query': 'Top 10 most used items this month', 'reason': 'Analyze consumption', 'priority': 'low'},
        {'query': 'Stock value by location', 'reason': 'Financial overview', 'priority': 'low'},
    ])

    return JsonResponse({'success': True, 'suggestions': suggestions[:6]})


@csrf_exempt
@require_GET
@admin_required
def ai_quick_actions(request):
    actions = [
        {'id': 'low_stock', 'label': 'Low Stock', 'icon': 'warning', 'query': 'Show low stock items'},
        {'id': 'expiring', 'label': 'Expiring', 'icon': 'clock', 'query': "What's expiring in 7 days?"},
        {'id': 'overview', 'label': 'Overview', 'icon': 'chart', 'query': 'Stock summary'},
        {'id': 'top_items', 'label': 'Top Items', 'icon': 'fire', 'query': 'Top 10 most used items'},
        {'id': 'pending', 'label': 'Pending POs', 'icon': 'truck', 'query': 'Show pending orders'},
        {'id': 'forecast', 'label': 'Forecast', 'icon': 'crystal-ball', 'query': 'When will items run out?'},
    ]
    return JsonResponse({'success': True, 'actions': actions})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
@admin_required
def ai_history(request):
    return JsonResponse({
        'success': True,
        'history': [],
        'message': 'History is managed client-side',
    })


@csrf_exempt
@require_POST
@admin_required
def ai_feedback(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    return JsonResponse({'success': True, 'message': 'Thank you for your feedback!'})
