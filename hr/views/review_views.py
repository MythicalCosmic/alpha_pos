from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import admin_required
from hr.services import ReviewService


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def reviews(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        result, status = ReviewService.list(page=page, per_page=per_page)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ReviewService.create(**data, created_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT"])
@admin_required
def review_detail(request, review_id):
    if request.method == "GET":
        result, status = ReviewService.get(review_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ReviewService.update(review_id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def review_submit(request, review_id):
    result, status = ReviewService.submit(review_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def review_acknowledge(request, review_id):
    result, status = ReviewService.acknowledge(review_id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def goals(request):
    if request.method == "GET":
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        result, status = ReviewService.list_goals(page=page, per_page=per_page)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ReviewService.create_goal(**data, created_by_id=request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "PUT"])
@admin_required
def goal_detail(request, goal_id):
    if request.method == "GET":
        result, status = ReviewService.get_goal(goal_id)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ReviewService.update_goal(goal_id, **data)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@admin_required
def goal_progress(request, goal_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    result, status = ReviewService.update_goal_progress(
        goal_id,
        progress_percent=data.get("progress_percent"),
        status=data.get("status"),
    )
    return JsonResponse(result, status=status)
