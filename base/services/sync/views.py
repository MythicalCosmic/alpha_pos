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


def _resolve_branch_token(token):
    # Prefer BRANCH_TOKEN_MAP ({token: branch_id}) which binds each token to a
    # single branch and lets us reject mismatched X-Branch-ID headers. Fall
    # back to the legacy ALLOWED_BRANCH_TOKENS list (no binding) if the map
    # isn't configured.
    from django.utils.crypto import constant_time_compare
    token_map = getattr(settings, 'BRANCH_TOKEN_MAP', None) or {}
    for known_token, bound_branch in token_map.items():
        if constant_time_compare(token, known_token):
            return bound_branch, True
    allowed_tokens = getattr(settings, 'ALLOWED_BRANCH_TOKENS', [])
    if allowed_tokens and any(constant_time_compare(token, t) for t in allowed_tokens):
        return None, True
    return None, False


def _management_authorized(request):
    # Management endpoints (status / trigger / queue / report …) expose internal
    # state and can trigger full pushes. The token is required unconditionally:
    # tying auth to DEBUG meant a deploy that booted with DEBUG=True (operator
    # error, env override) would expose unauthenticated control endpoints.
    # Local devs set SYNC_MANAGEMENT_TOKEN in their .env explicitly.
    from django.utils.crypto import constant_time_compare
    expected = getattr(settings, 'SYNC_MANAGEMENT_TOKEN', '') or ''
    if not expected:
        return False
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    prefix = 'Management '
    if not auth.startswith(prefix):
        return False
    return constant_time_compare(auth[len(prefix):], expected)


def _management_denied():
    return JsonResponse(
        {'error': 'Sync management endpoint requires Authorization: Management <token>'},
        status=401,
    )


@csrf_exempt
@require_POST
def receive(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Branch ') and not auth.startswith('Cloud '):
        return JsonResponse({'error': 'Invalid authorization'}, status=401)

    bound_branch = None
    if auth.startswith('Cloud '):
        from django.utils.crypto import constant_time_compare
        token = auth[6:]
        expected = getattr(settings, 'CLOUD_SYNC_TOKEN', '')
        if not expected or not constant_time_compare(token, expected):
            return JsonResponse({'error': 'Invalid cloud token'}, status=401)
    elif auth.startswith('Branch '):
        token = auth[7:]
        bound_branch, ok = _resolve_branch_token(token)
        if not ok:
            return JsonResponse({'error': 'Invalid branch token'}, status=401)

    branch_id = request.META.get('HTTP_X_BRANCH_ID', 'unknown')

    # If the token was bound to a specific branch, the caller cannot claim a
    # different branch_id — otherwise any holder of any valid token could
    # write records as another branch and poison per-branch filtering.
    if bound_branch is not None and branch_id not in (bound_branch, 'unknown'):
        return JsonResponse(
            {'error': f'X-Branch-ID does not match token (expected {bound_branch})'},
            status=403,
        )
    if bound_branch is not None:
        branch_id = bound_branch

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
    if not _management_authorized(request):
        return _management_denied()

    from base.services.sync.service import SyncService
    from base.services.sync.config import SyncConfig

    if not SyncConfig.is_enabled():
        return JsonResponse({'enabled': False, 'message': 'Sync not enabled'})

    return JsonResponse(SyncService.get_status())


@csrf_exempt
@require_POST
def trigger(request):
    if not _management_authorized(request):
        return _management_denied()

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
    if not _management_authorized(request):
        return _management_denied()

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
    if not _management_authorized(request):
        return _management_denied()

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
    if not _management_authorized(request):
        return _management_denied()

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
    if not _management_authorized(request):
        return _management_denied()

    from base.services.sync.service import SyncService
    return JsonResponse(SyncService.status_report())


@csrf_exempt
@require_GET
def changes(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Branch '):
        return JsonResponse({'error': 'Invalid authorization'}, status=401)

    token = auth[7:]
    bound_branch, ok = _resolve_branch_token(token)
    if not ok:
        return JsonResponse({'error': 'Invalid branch token'}, status=401)

    from base.services.sync.config import SYNC_ORDER, get_all_models
    from base.services.sync.service import SyncService
    from django.utils.dateparse import parse_datetime

    requesting_branch = request.META.get('HTTP_X_BRANCH_ID', '')
    if bound_branch is not None:
        if requesting_branch and requesting_branch != bound_branch:
            return JsonResponse(
                {'error': f'X-Branch-ID does not match token (expected {bound_branch})'},
                status=403,
            )
        requesting_branch = bound_branch
    since_param = request.GET.get('since')
    since_dt = parse_datetime(since_param) if since_param else None
    try:
        per_page = min(max(1, int(request.GET.get('per_page', 1000))), 5000)
    except (TypeError, ValueError):
        per_page = 1000

    models = get_all_models()
    data = {}
    total_records = 0
    has_more = False

    for name in SYNC_ORDER:
        model_class = models.get(name)
        if not model_class:
            continue

        if since_dt:
            records = SyncService.get_changes_after(model_class, since_dt)
        else:
            all_objs = model_class.objects.all()[:per_page + 1]
            records = [obj.to_sync_dict() for obj in all_objs]
            if len(records) > per_page:
                records = records[:per_page]
                has_more = True

        if requesting_branch:
            records = [r for r in records if r.get('branch_id') != requesting_branch]

        if records:
            data[name] = records
            total_records += len(records)

    from django.utils import timezone
    return JsonResponse({
        'success': True,
        'data': data,
        'total_records': total_records,
        'has_more': has_more,
        'server_timestamp': timezone.now().isoformat(),
    })


@csrf_exempt
@require_POST
def trigger_pull(request):
    if not _management_authorized(request):
        return _management_denied()

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
