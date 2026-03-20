from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.conf import settings
from base.helpers.request import parse_json_body
from base.helpers.response import json_response


@csrf_exempt
@require_GET
def health(request):
    from base.services.sync.config import SyncConfig
    return JsonResponse({
        'status': 'ok',
        'mode': getattr(settings, 'DEPLOYMENT_MODE', 'unknown'),
        'sync_enabled': SyncConfig.is_enabled(),
    })


@csrf_exempt
@require_POST
def receive(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Branch '):
        return JsonResponse({'error': 'Invalid authorization'}, status=401)

    branch_id = request.META.get('HTTP_X_BRANCH_ID', 'unknown')

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    if isinstance(data, list):
        if not data:
            return JsonResponse({'error': 'Empty records'}, status=400)
        model_name = data[0].get('model_name', 'order')
        records = [item.get('data', item) for item in data]
    else:
        model_name = data.get('model')
        records = data.get('records', [])

    if not model_name or not records:
        return JsonResponse({'error': 'Missing model or records'}, status=400)

    from base.services.sync.receiver import CloudReceiver
    result = CloudReceiver.receive_batch(model_name, branch_id, records)

    return JsonResponse(result)


@csrf_exempt
@require_GET
def status(request):
    from base.services.sync.service import SyncService
    from base.services.sync.config import SyncConfig

    if not SyncConfig.is_enabled():
        return JsonResponse({'enabled': False, 'message': 'Sync not enabled'})

    return JsonResponse(SyncService.get_status())


@csrf_exempt
@require_POST
def trigger(request):
    from base.services.sync.service import SyncService
    from base.services.sync.config import SyncConfig, is_local_mode

    if not SyncConfig.is_enabled():
        return JsonResponse({'success': False, 'message': 'Sync not enabled'}, status=400)

    if not is_local_mode():
        return JsonResponse({'success': False, 'message': 'Only available in local mode'}, status=400)

    result = SyncService.push()
    return JsonResponse(result)


@csrf_exempt
@require_POST
def full_push(request):
    from base.services.sync.service import SyncService
    from base.services.sync.config import SyncConfig, is_local_mode

    if not SyncConfig.is_enabled():
        return JsonResponse({'success': False, 'message': 'Sync not enabled'}, status=400)

    if not is_local_mode():
        return JsonResponse({'success': False, 'message': 'Only available in local mode'}, status=400)

    result = SyncService.full_push()
    return JsonResponse(result)


@csrf_exempt
@require_GET
def queue_view(request):
    from base.services.sync.queue import SyncQueue

    records = SyncQueue.get_all()
    return JsonResponse({
        'count': len(records),
        'records': [{
            'model': r['model_name'],
            'uuid': r['uuid'],
            'created_at': r.get('created_at'),
            'attempts': r.get('attempts', 0),
            'last_error': r.get('last_error'),
        } for r in records[:100]],
    })


@csrf_exempt
@require_http_methods(["DELETE"])
def queue_clear(request):
    confirm = request.GET.get('confirm', '').lower() == 'true'
    if not confirm:
        return JsonResponse({
            'error': 'Add ?confirm=true to clear queue',
        }, status=400)

    from base.services.sync.queue import SyncQueue
    SyncQueue.clear()
    return JsonResponse({'success': True, 'message': 'Queue cleared'})


@csrf_exempt
@require_GET
def report(request):
    from base.services.sync.service import SyncService
    return JsonResponse(SyncService.status_report())


def get_sync_urls():
    from django.urls import path
    return [
        path('health', health, name='sync-health'),
        path('receive', receive, name='sync-receive'),
        path('status', status, name='sync-status'),
        path('trigger', trigger, name='sync-trigger'),
        path('full-push', full_push, name='sync-full-push'),
        path('queue', queue_view, name='sync-queue'),
        path('queue/clear', queue_clear, name='sync-queue-clear'),
        path('report', report, name='sync-report'),
    ]
