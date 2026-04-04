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
    if not auth.startswith('Branch ') and not auth.startswith('Cloud '):
        return JsonResponse({'error': 'Invalid authorization'}, status=401)

    if auth.startswith('Cloud '):
        token = auth[6:]
        expected = getattr(settings, 'CLOUD_SYNC_TOKEN', '')
        if not expected or token != expected:
            return JsonResponse({'error': 'Invalid cloud token'}, status=401)

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


@csrf_exempt
@require_GET
def changes(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Branch '):
        return JsonResponse({'error': 'Invalid authorization'}, status=401)

    from base.services.sync.config import SYNC_ORDER, get_all_models
    from base.services.sync.service import SyncService
    from django.utils.dateparse import parse_datetime

    requesting_branch = request.META.get('HTTP_X_BRANCH_ID', '')
    since_param = request.GET.get('since')
    since_dt = parse_datetime(since_param) if since_param else None

    models = get_all_models()
    data = {}

    for name in SYNC_ORDER:
        model_class = models.get(name)
        if not model_class:
            continue

        if since_dt:
            records = SyncService.get_changes_after(model_class, since_dt)
        else:
            records = [obj.to_sync_dict() for obj in model_class.objects.all()[:5000]]

        if requesting_branch:
            records = [r for r in records if r.get('branch_id') != requesting_branch]

        if records:
            data[name] = records

    from django.utils import timezone
    return JsonResponse({
        'success': True,
        'data': data,
        'server_timestamp': timezone.now().isoformat(),
    })


@csrf_exempt
@require_POST
def trigger_pull(request):
    from base.services.sync.service import SyncService
    from base.services.sync.config import SyncConfig, is_local_mode

    if not SyncConfig.is_enabled():
        return JsonResponse({'success': False, 'message': 'Sync not enabled'}, status=400)

    if not is_local_mode():
        return JsonResponse({'success': False, 'message': 'Only available in local mode'}, status=400)

    result = SyncService.pull_from_cloud()
    return JsonResponse(result)


def get_sync_urls():
    from django.urls import path
    return [
        path('health', health, name='sync-health'),
        path('receive', receive, name='sync-receive'),
        path('status', status, name='sync-status'),
        path('trigger', trigger, name='sync-trigger'),
        path('trigger-pull', trigger_pull, name='sync-trigger-pull'),
        path('full-push', full_push, name='sync-full-push'),
        path('changes', changes, name='sync-changes'),
        path('queue', queue_view, name='sync-queue'),
        path('queue/clear', queue_clear, name='sync-queue-clear'),
        path('report', report, name='sync-report'),
    ]
