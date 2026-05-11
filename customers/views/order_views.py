from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from base.helpers.request import parse_json_body, validate_pagination
from base.helpers.response import json_response
from base.security.auth import login_required
from base.security.audit import audit
from base.models import AuditLog
from customers.services.order_service import CustomerOrderService
from customers.requests.order_requests import create_order_request


@csrf_exempt
@require_GET
@login_required
def list_orders(request):
    page, per_page = validate_pagination(request)
    payment_status = request.GET.get('payment_status')
    statuses = request.GET.get('statuses')
    category_ids = request.GET.get('category_ids')
    user_id = request.GET.get('user_id')
    cashier_id = request.GET.get('cashier_id')
    order_by = request.GET.get('order_by', '-created_at')

    result, status_code = CustomerOrderService.get_all_orders(
        page=page, per_page=per_page, payment_status=payment_status,
        statuses=statuses, category_ids=category_ids, user_id=user_id,
        cashier_id=cashier_id, order_by=order_by,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
def get_order(request, order_id):
    result, status_code = CustomerOrderService.get_order_by_id(
        order_id, user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def create_order(request):
    data, error = create_order_request(request)
    if error:
        return json_response(error)

    user = request.user
    cashier_id = user.id if user.role == 'CASHIER' else None

    result, status_code = CustomerOrderService.create_order(
        user_id=user.id,
        items=data['items'],
        order_type=data.get('order_type', 'HALL'),
        phone_number=data.get('phone_number'),
        description=data.get('description'),
        cashier_id=cashier_id,
        delivery_person_id=data.get('delivery_person_id'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def add_item(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)

    if not product_id:
        return json_response(({
            "success": False,
            "message": "Missing product_id",
            "errors": {"product_id": "product_id is required"}
        }, 422))

    if quantity <= 0:
        return json_response(({
            "success": False,
            "message": "Invalid quantity",
            "errors": {"quantity": "quantity must be greater than 0"}
        }, 422))

    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.add_item_to_order(
        order_id, product_id, quantity, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
def update_item(request, order_id, item_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    quantity = data.get('quantity')
    if not quantity or quantity <= 0:
        return json_response(({
            "success": False,
            "message": "Invalid quantity",
            "errors": {"quantity": "quantity must be greater than 0"}
        }, 422))

    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.update_order_item(
        order_id, item_id, quantity, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def remove_item(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.remove_item_from_order(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
def update_status(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    status = data.get('status')
    if not status:
        return json_response(({
            "success": False,
            "message": "Missing status",
            "errors": {"status": "status is required"}
        }, 422))

    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.update_order_status(
        order_id, status, cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def pay_order(request, order_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.mark_as_paid(
        order_id, cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def mark_ready(request, order_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.mark_order_ready(
        order_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def mark_item_ready(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.mark_item_ready(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def unmark_item_ready(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.unmark_item_ready(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def cancel_order(request, order_id):
    cashier_id = request.user.id if request.user.role == 'CASHIER' else None
    result, status_code = CustomerOrderService.update_order_status(
        order_id, 'CANCELED', cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    if result.get('success'):
        audit(
            request,
            AuditLog.Action.ORDER_CANCEL,
            target_type='Order',
            target_id=order_id,
            metadata={'role': request.user.role},
        )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
def client_display(request):
    result, status_code = CustomerOrderService.get_client_display_orders()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
def chef_display(request):
    result, status_code = CustomerOrderService.get_chef_display_orders()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
def apply_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.apply_to_order(order_id, data.get('code', ''), request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
def remove_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.remove_from_order(order_id, data.get('order_discount_id'), request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
def check_secret_word(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.validate_secret_word(data.get('word', ''), order_id, request.user.id)
    return JsonResponse(result, status=status)
