from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from notifications.services.config_service import ConfigService
from notifications.services.sender_service import SenderService
from notifications.services.queue_service import QueueService
from notifications.models import NotificationTemplate, NotificationLog


@csrf_exempt
@require_http_methods(["GET", "PUT"])
@admin_required
def settings_view(request):
    if request.method == "GET":
        return json_response(ConfigService.get_settings())

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    return json_response(ConfigService.update_settings(**data))


@csrf_exempt
@require_POST
@admin_required
def settings_test(request):
    settings = ConfigService.get_settings_obj()
    brand = settings.brand_name if settings else 'Alpha POS'
    return json_response(SenderService.send_raw(f"{brand} - test notification"))


@require_GET
@admin_required
def settings_status(request):
    return json_response(ConfigService.get_status())


@require_GET
@admin_required
def notification_types(request):
    templates = NotificationTemplate.objects.all()
    data = [
        {
            "id": t.id,
            "notification_type": t.notification_type,
            "name": t.name,
            "is_enabled": t.is_enabled,
        }
        for t in templates
    ]
    return JsonResponse({"success": True, "data": data}, status=200)


@csrf_exempt
@require_http_methods(["PUT"])
@admin_required
def notification_type_detail(request, type_slug):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    try:
        template = NotificationTemplate.objects.get(notification_type=type_slug)
    except NotificationTemplate.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Notification type not found"}, status=404
        )

    if "is_enabled" in data:
        template.is_enabled = data["is_enabled"]
    if "template_text" in data:
        template.template_text = data["template_text"]
    template.save()

    return JsonResponse(
        {
            "success": True,
            "message": "Updated",
            "data": {
                "id": template.id,
                "notification_type": template.notification_type,
                "name": template.name,
                "template_text": template.template_text,
                "is_enabled": template.is_enabled,
            },
        },
        status=200,
    )


@require_GET
@admin_required
def templates_list(request):
    templates = NotificationTemplate.objects.all()
    data = [
        {
            "id": t.id,
            "notification_type": t.notification_type,
            "name": t.name,
            "template_text": t.template_text,
            "is_enabled": t.is_enabled,
            "language": t.language,
        }
        for t in templates
    ]
    return JsonResponse({"success": True, "data": data}, status=200)


@csrf_exempt
@require_http_methods(["GET", "PUT"])
@admin_required
def template_detail(request, template_id):
    try:
        template = NotificationTemplate.objects.get(id=template_id)
    except NotificationTemplate.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Template not found"}, status=404
        )

    if request.method == "GET":
        return JsonResponse(
            {
                "success": True,
                "data": {
                    "id": template.id,
                    "notification_type": template.notification_type,
                    "name": template.name,
                    "template_text": template.template_text,
                    "is_enabled": template.is_enabled,
                    "language": template.language,
                },
            },
            status=200,
        )

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    if "template_text" in data:
        template.template_text = data["template_text"]
    template.save()

    return JsonResponse(
        {
            "success": True,
            "message": "Updated",
            "data": {
                "id": template.id,
                "notification_type": template.notification_type,
                "name": template.name,
                "template_text": template.template_text,
                "is_enabled": template.is_enabled,
                "language": template.language,
            },
        },
        status=200,
    )


@require_GET
@admin_required
def queue_view(request):
    items = QueueService.get_all()
    return JsonResponse({'success': True, 'data': {'queue': items, 'count': len(items)}})


@csrf_exempt
@require_POST
@admin_required
def queue_process(request):
    sent, failed = QueueService.process()
    return JsonResponse({'success': True, 'data': {'sent': sent, 'failed': failed}})


@csrf_exempt
@require_POST
@admin_required
def queue_clear(request):
    QueueService.clear()
    return JsonResponse({'success': True, 'message': 'Queue cleared'})


@require_GET
@admin_required
def logs_view(request):
    page = int(request.GET.get("page", 1))
    per_page = int(request.GET.get("per_page", 25))
    notification_type = request.GET.get("notification_type")

    qs = NotificationLog.objects.all()
    if notification_type:
        qs = qs.filter(notification_type=notification_type)

    total = qs.count()
    start = (page - 1) * per_page
    end = start + per_page
    logs = qs[start:end]

    data = [
        {
            "id": log.id,
            "notification_type": log.notification_type,
            "recipient": log.recipient,
            "message_text": log.message_text,
            "status": log.status,
            "error_message": log.error_message,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]

    return JsonResponse(
        {
            "success": True,
            "data": data,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        },
        status=200,
    )
