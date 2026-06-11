import logging

logger = logging.getLogger(__name__)
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from base.repositories import OrderRepository, OrderItemRepository, ProductRepository, UserRepository, DeliveryPersonRepository, PlaceRepository, TableRepository
from base.services.inkassa_service import InkassaService
from base.helpers.response import ServiceResponse
from notifications.handlers.order import OrderNotification


ALLOWED_STATUSES = ['PREPARING', 'READY', 'CANCELED']

# The POS frontend (smart-pos) keys its filters and badges on the spelling
# `CANCELLED` (double L) — see issue #16. The Django model stores `CANCELED`
# (single L). Normalize at this API boundary so the wire contract is always
# the double-L spelling while the DB value is left untouched (no migration).
def _to_api_status(status):
    """Internal status -> wire status (CANCELED -> CANCELLED)."""
    return 'CANCELLED' if status == 'CANCELED' else status


def _from_api_status(status):
    """Wire status -> internal status (CANCELLED -> CANCELED).

    Accepts either spelling so both old and new clients work, and is
    case-insensitive for robustness.
    """
    if not status:
        return status
    s = status.strip().upper()
    return 'CANCELED' if s == 'CANCELLED' else s

ALLOWED_ORDER_FIELDS = {
    'created_at', '-created_at', 'updated_at', '-updated_at',
    'total_amount', '-total_amount', 'display_id', '-display_id',
    'status', '-status', 'id', '-id',
}


def _format_duration(seconds):
    if seconds is None:
        return None
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _serialize_order_list(order):
    return {
        'id': order.id,
        'display_id': order.display_id,
        'order_type': order.order_type,
        'phone_number': order.phone_number,
        'description': order.description,
        'cashier': {
            'id': order.cashier.id,
            'name': f"{order.cashier.first_name} {order.cashier.last_name}"
        } if order.cashier else None,
        'status': _to_api_status(order.status),
        'is_paid': order.is_paid,
        'total_amount': str(order.total_amount or 0),
        'discount_percent': str(order.discount_percent or 0),
        'payments': [{'method': p.method, 'amount': str(p.amount)}
                     for p in order.payments.all()],
        'place': {'id': order.place.id, 'name': order.place.name} if order.place else None,
        'table': {'id': order.table.id, 'number': order.table.number} if order.table else None,
        # The list queryset is prefetched with `items__product__category`
        # (OrderRepository.get_with_relations) — iterate the cached items
        # instead of `.values()`, which would issue a fresh query per order
        # and defeat the prefetch (200+ extra hits on the client_display).
        'items': [
            {
                'id': i.id,
                'product__id': i.product_id,
                'product__name': i.product.name if i.product else None,
                'product__category__id': i.product.category_id if i.product else None,
                'product__category__name': (
                    i.product.category.name if i.product and i.product.category else None
                ),
                'quantity': i.quantity,
                'detail': i.detail,
                'price': i.price,
                'ready_at': i.ready_at,
            }
            for i in order.items.all()
        ],
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
        'ready_at': order.ready_at.isoformat() if order.ready_at else None,
        'created_at': order.created_at.isoformat(),
        'updated_at': order.updated_at.isoformat(),
    }


def _serialize_order_detail(order):
    items = []
    for item in order.items.all():
        prep_time = (item.ready_at - order.created_at).total_seconds() if item.ready_at else None
        items.append({
            'id': item.id,
            'product': {
                'id': item.product.id,
                'name': item.product.name,
                'category': item.product.category.name if item.product.category else None,
            },
            'quantity': item.quantity,
            'price': str(item.price),
            'subtotal': str(item.price * item.quantity),
            'detail': item.detail,
            'ready_at': item.ready_at.isoformat() if item.ready_at else None,
            'is_ready': item.ready_at is not None,
            'preparation_time_seconds': prep_time,
            'preparation_time_formatted': _format_duration(prep_time) if prep_time else None,
        })

    order_prep_time = (order.ready_at - order.created_at).total_seconds() if order.ready_at else None

    return {
        'id': order.id,
        'display_id': order.display_id,
        'order_type': order.order_type,
        'phone_number': order.phone_number,
        'description': order.description,
        'user': {
            'id': order.user.id,
            'name': f"{order.user.first_name} {order.user.last_name}",
            'email': order.user.email,
        },
        'cashier': {
            'id': order.cashier.id,
            'name': f"{order.cashier.first_name} {order.cashier.last_name}"
        } if order.cashier else None,
        'place': {'id': order.place.id, 'name': order.place.name} if order.place else None,
        'table': {'id': order.table.id, 'number': order.table.number} if order.table else None,
        'status': _to_api_status(order.status),
        'is_paid': order.is_paid,
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
        'total_amount': str(order.total_amount),
        'discount_percent': str(order.discount_percent or 0),
        'payments': [{'method': p.method, 'amount': str(p.amount)}
                     for p in order.payments.all()],
        'items': items,
        'items_ready_count': sum(1 for i in items if i['is_ready']),
        'items_total_count': len(items),
        'created_at': order.created_at.isoformat(),
        'updated_at': order.updated_at.isoformat(),
        'ready_at': order.ready_at.isoformat() if order.ready_at else None,
        'preparation_time_seconds': order_prep_time,
        'preparation_time_formatted': _format_duration(order_prep_time) if order_prep_time else None,
    }


def _check_cashier_ownership(order, cashier_id, user_id=None, user_role=None):
    # Shared-monoblock model: ANY POS staff may act on ANY order. Multiple
    # cashiers share one till and the kitchen (KDS) marks orders ready, so
    # blocking a cashier from an order another cashier opened breaks the
    # normal flow (mark-ready / pay / status / items). Ownership therefore
    # only constrains self-service customers (USER), who must own the order
    # they touch.
    if user_role in ('ADMIN', 'MANAGER', 'CASHIER'):
        return None
    # USER (or any other role): require ownership of the order itself.
    if user_id is not None and order.user_id != user_id:
        return ServiceResponse.forbidden(
            f'You do not have permission to modify order #{order.display_id}.'
        )
    # Legacy fallback when caller did not supply role/user_id.
    if order.cashier_id and order.cashier_id != cashier_id:
        return ServiceResponse.forbidden(
            f'You do not have permission to modify this order. Order #{order.display_id} was created by another cashier.'
        )
    return None


def _parse_statuses(statuses_param):
    if not statuses_param:
        return None
    param = statuses_param.strip().strip('[]')
    if not param:
        return None
    # Map each requested status through the boundary so a frontend filter of
    # `statuses=CANCELLED` matches the stored `CANCELED` rows.
    return [
        _from_api_status(s.strip().strip('"\''))
        for s in param.split(',') if s.strip()
    ]


def _parse_int_list(param):
    if not param:
        return None
    param = param.strip().strip('[]')
    if not param:
        return None
    result = []
    for item in param.split(','):
        item = item.strip().strip('"\'')
        if item.isdigit():
            result.append(int(item))
    return result or None


def _recalculate_total(order):
    from discounts.repositories import OrderDiscountRepository
    from discounts.services.discount_service import DiscountService

    order.subtotal = OrderItemRepository.calculate_order_total(order)
    # Recompute each applied discount against the *current* items rather than
    # trusting the frozen OrderDiscount.discount_amount. A percentage / BUY_X /
    # FREE_ITEM rule frozen at apply-time goes stale the moment items change:
    # if the order grew the customer is over-charged, if it shrank the drawer is
    # under-credited (mark_as_paid would settle the wrong cash, or drive
    # total_amount negative and *remove* real cash via add_to_register). The
    # OrderDiscount rows are the source of truth — refresh them, then sum.
    order_items = list(order.items.select_related('product__category').all())
    applied = Decimal('0')
    for od in OrderDiscountRepository.get_for_order(order.id).select_related(
        'discount__discount_type'
    ):
        new_amount = DiscountService.calculate_discount(od.discount, order_items)
        if new_amount != od.discount_amount:
            od.discount_amount = new_amount
            od.save(update_fields=['discount_amount'])
        applied += new_amount
    order.discount_amount = min(applied, order.subtotal)
    order.total_amount = max(Decimal('0'), order.subtotal - order.discount_amount)
    order.save(update_fields=['subtotal', 'discount_amount', 'total_amount'])


def _fiscalize_after_pay(order_id):
    # Serve-now policy: fiscalization must never break the pay flow. The service
    # call self-gates (no-op when disabled) and never raises.
    try:
        from fiscalization.services import FiscalizationService
        FiscalizationService.fiscalize_on_payment(order_id)
    except Exception:
        logger.exception('non-critical fiscalization error in pay flow (order=%s)', order_id)


def _adjust_order_stock(order_id, product_id, quantity_delta, performed_by_id):
    # Keep ingredient stock in sync when an already-deducted order's lines
    # change. adjust_for_item_change self-gates: it's a no-op unless the order
    # had prior deductions, so this is safe to call regardless of config.
    if quantity_delta == 0:
        return
    try:
        from stock.services import OrderStockService, StockSettingsService
        location_id = StockSettingsService.get_default_location_id()
        if location_id:
            OrderStockService.adjust_for_item_change(
                order_id, product_id, quantity_delta, location_id, performed_by_id,
            )
    except Exception:
        logger.exception('non-critical stock-adjust error in order edit flow')


def _check_and_update_ready(order):
    total = order.items.count()
    ready = order.items.filter(ready_at__isnull=False).count()
    all_ready = total > 0 and total == ready

    if all_ready and order.status != 'READY':
        order.status = 'READY'
        order.ready_at = timezone.now()
        order.save(update_fields=['status', 'ready_at'])
        return True, True

    return all_ready, False


class CustomerOrderService:

    @staticmethod
    def get_all_orders(page=1, per_page=20, statuses=None, payment_status=None,
                       category_ids=None, user_id=None, cashier_id=None,
                       order_by='-created_at'):
        statuses_list = _parse_statuses(statuses)
        category_ids_list = _parse_int_list(category_ids)

        if order_by not in ALLOWED_ORDER_FIELDS:
            order_by = '-created_at'

        qs = OrderRepository.build_filtered_queryset(
            statuses=statuses_list,
            payment_status=payment_status,
            category_ids=category_ids_list,
            user_id=user_id,
            cashier_id=cashier_id,
            order_by=order_by,
        )

        page_obj, paginator = OrderRepository.paginate(qs, page, per_page)
        orders = [_serialize_order_list(o) for o in page_obj.object_list]

        return ServiceResponse.success(data={
            'orders': orders,
            'filters': {
                'statuses': statuses_list,
                'category_ids': category_ids_list,
                'payment_status': payment_status,
            },
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_orders': paginator.count,
                'per_page': per_page,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
        })

    @staticmethod
    def get_order_by_id(order_id, user_id=None, user_role=None):
        order = OrderRepository.get_by_id_with_relations(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')
        # Read-side ownership: staff (ADMIN/CASHIER/MANAGER/WAITER) may read any
        # order; a plain USER only their own.
        if user_role not in ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER') and user_id is not None and order.user_id != user_id:
            return ServiceResponse.forbidden(
                f'You do not have permission to view order #{order.display_id}.'
            )
        return ServiceResponse.success(data={'order': _serialize_order_detail(order)})

    @staticmethod
    @transaction.atomic
    def create_order(user_id, items, order_type='HALL', phone_number=None,
                     description=None, cashier_id=None, delivery_person_id=None,
                     place_id=None, table_id=None):
        if not UserRepository.exists(id=user_id):
            return ServiceResponse.not_found('User not found')

        if cashier_id and not UserRepository.exists(id=cashier_id, role__in=['CASHIER', 'MANAGER']):
            return ServiceResponse.error('Invalid cashier')

        if not items:
            return ServiceResponse.validation_error(
                errors={'items': 'At least one item is required'},
                message='Order must have at least one item',
            )

        if order_type not in ['HALL', 'DELIVERY', 'PICKUP']:
            return ServiceResponse.validation_error(
                errors={'order_type': 'Must be HALL, DELIVERY, or PICKUP'},
                message='Invalid order type',
            )

        delivery_person = None
        if delivery_person_id:
            delivery_person = DeliveryPersonRepository.get_by_id(delivery_person_id)
            if not delivery_person:
                return ServiceResponse.not_found('Delivery person not found')

        place = None
        if place_id:
            place = PlaceRepository.get_by_id(place_id)
            if not place:
                return ServiceResponse.not_found('Place not found')

        table = None
        if table_id:
            table = TableRepository.get_by_id(table_id)
            if not table:
                return ServiceResponse.not_found('Table not found')

        display_id = OrderRepository.next_display_id()
        chef_queue_number = OrderRepository.next_chef_queue_number()

        product_ids = [item.get('product_id') for item in items]
        products = {p.id: p for p in ProductRepository.filter(id__in=product_ids)}

        total_amount = Decimal('0.00')
        order_items_data = []

        for item_data in items:
            product_id = item_data.get('product_id')
            quantity = item_data.get('quantity', 1)

            if quantity <= 0:
                return ServiceResponse.validation_error(
                    errors={'quantity': 'Must be greater than 0'},
                    message='Quantity must be greater than 0',
                )

            product = products.get(product_id)
            if not product:
                return ServiceResponse.not_found(f'Product with id {product_id} not found')

            order_items_data.append({
                'product': product,
                'detail': item_data.get('detail'),
                'quantity': quantity,
                'price': product.price,
            })
            total_amount += product.price * quantity

        order = OrderRepository.create(
            user_id=user_id,
            cashier_id=cashier_id,
            display_id=display_id,
            chef_queue_number=chef_queue_number,
            order_type=order_type,
            phone_number=phone_number,
            description=description,
            status='PREPARING',
            is_paid=False,
            subtotal=total_amount,
            total_amount=total_amount,
            delivery_person=delivery_person,
            place=place,
            table=table,
        )

        from base.models import OrderItem
        now = timezone.now()
        # Instant items (drinks, packaged goods) need no kitchen prep, so they
        # are born ready and never hit the chef display. Non-instant items are
        # created unready for the kitchen to work through.
        any_kitchen_item = False
        new_items = []
        for d in order_items_data:
            instant = d['product'].is_instant
            if not instant:
                any_kitchen_item = True
            new_items.append(OrderItem(
                order=order,
                product=d['product'],
                detail=d['detail'],
                quantity=d['quantity'],
                price=d['price'],
                ready_at=now if instant else None,
            ))
        OrderItem.objects.bulk_create(new_items)

        # An order made up entirely of instant items has nothing to cook —
        # it's ready the moment it's placed.
        if not any_kitchen_item:
            order.status = 'READY'
            order.ready_at = now
            order.save(update_fields=['status', 'ready_at'])

        fresh = OrderRepository.get_by_id_with_relations(order.id)
        if fresh:
            OrderNotification.on_new_order(fresh)

        try:
            from stock.services import OrderStatusHandler, StockSettingsService
            location_id = StockSettingsService.get_default_location_id()
            if location_id:
                stock_items = [
                    {'product_id': d['product'].id, 'quantity': d['quantity']}
                    for d in order_items_data
                ]
                OrderStatusHandler.on_status_change(
                    order.id, None, 'PREPARING', stock_items, location_id, user_id,
                )
        except Exception:
            logger.exception('non-critical stock-handler error in order flow')

        return ServiceResponse.created(
            data={'order_id': order.id, 'display_id': order.display_id},
            message='Order created successfully',
        )

    @staticmethod
    @transaction.atomic
    def add_item_to_order(order_id, product_id, quantity, cashier_id=None, user_id=None, user_role=None):
        # Row-lock the order so concurrent add-item calls serialize across
        # both the quantity increment and the subtotal recalculate.
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.is_paid:
            # A paid order's total was already credited to the cash register on
            # payment. Editing items afterwards rewrites total_amount with no
            # matching register adjustment, desyncing the drawer. Block it.
            return ServiceResponse.error('Cannot modify an order that has already been paid')

        if order.status != 'PREPARING':
            return ServiceResponse.error('Cannot modify order that is not in PREPARING status')

        product = ProductRepository.get_by_id(product_id)
        if not product:
            return ServiceResponse.not_found('Product not found')

        # A zero/negative quantity flows straight into F('quantity') + quantity
        # and the subtotal recalculate, producing a negative line and a negative
        # order total that then removes cash from the register on payment.
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            return ServiceResponse.validation_error(
                errors={'quantity': 'Must be a positive integer'},
                message='Quantity must be greater than 0',
            )

        is_instant = product.is_instant
        existing = OrderItemRepository.get_existing_unready(order_id, product_id)
        if existing and not is_instant:
            # Increment in SQL so concurrent add-item calls cannot lose updates.
            from django.db.models import F
            OrderItemRepository.model.objects.filter(pk=existing.pk).update(
                quantity=F('quantity') + quantity,
            )
        else:
            # Instant items are born ready and never need the kitchen.
            OrderItemRepository.create(
                order=order, product=product, quantity=quantity,
                price=product.price,
                ready_at=timezone.now() if is_instant else None,
            )

        # Only adding a real (non-instant) item reopens a ready order for the
        # kitchen; tacking on a drink must not send the order back to PREPARING.
        if not is_instant and order.ready_at:
            order.ready_at = None
            order.status = 'PREPARING'
            order.save(update_fields=['ready_at', 'status'])

        _recalculate_total(order)
        _adjust_order_stock(order_id, product_id, quantity, cashier_id or user_id)
        return ServiceResponse.success(message='Item added to order successfully')

    @staticmethod
    @transaction.atomic
    def update_order_item(order_id, item_id, quantity, cashier_id=None, user_id=None, user_role=None):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.is_paid:
            # A paid order's total was already credited to the cash register on
            # payment. Editing items afterwards rewrites total_amount with no
            # matching register adjustment, desyncing the drawer. Block it.
            return ServiceResponse.error('Cannot modify an order that has already been paid')

        if order.status != 'PREPARING':
            return ServiceResponse.error('Cannot modify order that is not in PREPARING status')

        if quantity <= 0:
            return ServiceResponse.validation_error(
                errors={'quantity': 'Must be greater than 0'},
                message='Quantity must be greater than 0',
            )

        item = OrderItemRepository.first(id=item_id, order_id=order_id)
        if not item:
            return ServiceResponse.not_found('Order item not found')

        old_quantity = item.quantity
        product_id = item.product_id
        item.quantity = quantity
        item.save(update_fields=['quantity'])
        _recalculate_total(order)
        _adjust_order_stock(order_id, product_id, quantity - old_quantity, cashier_id or user_id)

        return ServiceResponse.success(message='Order item updated successfully')

    @staticmethod
    @transaction.atomic
    def remove_item_from_order(order_id, item_id, cashier_id=None, user_id=None, user_role=None):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.is_paid:
            # A paid order's total was already credited to the cash register on
            # payment. Editing items afterwards rewrites total_amount with no
            # matching register adjustment, desyncing the drawer. Block it.
            return ServiceResponse.error('Cannot modify an order that has already been paid')

        if order.status != 'PREPARING':
            return ServiceResponse.error('Cannot modify order that is not in PREPARING status')

        item = OrderItemRepository.first(id=item_id, order_id=order_id)
        if not item:
            return ServiceResponse.not_found('Order item not found')

        product_id = item.product_id
        removed_quantity = item.quantity
        item.delete(hard_delete=True)

        # Return ingredient stock for the removed line *before* any order
        # deletion: Order FK on StockTransaction is SET_NULL, so hard-deleting
        # the order first would strand the deductions with no way to reverse.
        _adjust_order_stock(order_id, product_id, -removed_quantity, cashier_id or user_id)

        if order.items.count() == 0:
            order.delete(hard_delete=True)
            return ServiceResponse.success(message='Order deleted (no items remaining)')

        _check_and_update_ready(order)
        _recalculate_total(order)
        return ServiceResponse.success(message='Item removed from order successfully')

    @staticmethod
    @transaction.atomic
    def update_order_status(order_id, status, cashier_id=None, user_id=None, user_role=None):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        status = _from_api_status(status)
        # Invalid enum value is a client contract error -> 422 (not 400), so
        # the frontend can distinguish "bad request shape" from "rejected".
        if status not in ALLOWED_STATUSES:
            return ServiceResponse.validation_error(
                errors={'status': f'Allowed: {", ".join(_to_api_status(s) for s in ALLOWED_STATUSES)}'},
                message='Invalid status',
            )

        if order.status == 'CANCELED':
            # Cancelling an already-cancelled order is idempotent: return 200
            # with the order, no repeated side-effects (the frontend may retry
            # on a flaky network). Any *other* target from CANCELED is an
            # illegal transition (the kitchen treats CANCELLED as terminal).
            if status == 'CANCELED':
                return CustomerOrderService.get_order_by_id(
                    order_id, user_id=user_id, user_role=user_role,
                )
            return ServiceResponse.validation_error(
                errors={'status': 'A cancelled order cannot change status'},
                message='Illegal status transition',
            )

        old_status = order.status
        update_fields = ['status']
        order.status = status

        if status == 'READY':
            now = timezone.now()
            order.ready_at = now
            order.items.filter(ready_at__isnull=True).update(ready_at=now)
            update_fields.append('ready_at')

        order.save(update_fields=update_fields)

        # Cancelling a paid order must reverse the cash-register entry,
        # otherwise the register over-reports balance while stock is
        # reverse-deducted by the handler below. Only cash reverses through
        # the drawer; card/Payme settle externally.
        if status == 'CANCELED' and order.is_paid:
            from base.models import OrderPayment
            from django.db.models import Sum
            pay_qs = OrderPayment.objects.filter(order=order)
            if pay_qs.exists():
                # Reverse exactly the cash share that hit the drawer = the bill
                # total minus what settled externally (card/Payme), so a MIXED
                # order reverses only its cash portion.
                noncash = pay_qs.exclude(method='CASH').aggregate(s=Sum('amount'))['s'] or Decimal('0')
                cash_in_drawer = Decimal(order.total_amount or 0) - noncash
            elif order.payment_method in ('CASH', None) and order.total_amount:
                # Legacy order (paid before per-line payments) — full reversal.
                cash_in_drawer = Decimal(order.total_amount or 0)
            else:
                cash_in_drawer = Decimal('0')
            if cash_in_drawer > 0:
                InkassaService.add_to_register(-cash_in_drawer)

        if status == 'READY':
            OrderNotification.on_order_ready(order_id)
        elif status == 'CANCELED':
            OrderNotification.on_order_cancelled(order_id)

        try:
            from stock.services import OrderStatusHandler, StockSettingsService
            location_id = StockSettingsService.get_default_location_id()
            if location_id:
                stock_items = [
                    {'product_id': i.product_id, 'quantity': i.quantity}
                    for i in order.items.all()
                ]
                OrderStatusHandler.on_status_change(
                    order.id, old_status, status, stock_items, location_id, order.user_id,
                )
        except Exception:
            logger.exception('non-critical stock-handler error in order flow')

        # Return the full updated order object (BE-1/BE-2 contract). Re-fetch
        # with relations so the serialized payload reflects the just-applied
        # status and ready_at.
        fresh = OrderRepository.get_by_id_with_relations(order_id)
        return ServiceResponse.success(
            data={
                'status': _to_api_status(status),
                'order': _serialize_order_detail(fresh) if fresh else None,
            },
            message=f'Order status updated to {_to_api_status(status)}',
        )

    @staticmethod
    @transaction.atomic
    def mark_item_ready(order_id, item_id, cashier_id=None, user_id=None, user_role=None):
        order = OrderRepository.get_by_id_with_relations(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Cannot modify cancelled order')

        if order.status == 'READY':
            return ServiceResponse.error('Order is already marked as ready')

        item = order.items.filter(id=item_id).first()
        if not item:
            return ServiceResponse.not_found('Order item not found')

        if item.ready_at is not None:
            return ServiceResponse.error('Item is already marked as ready')

        now = timezone.now()
        item.ready_at = now
        item.save(update_fields=['ready_at'])

        item_prep_time = (item.ready_at - order.created_at).total_seconds()
        all_ready, order_became_ready = _check_and_update_ready(order)

        order_prep_time = None
        if order_became_ready and order.ready_at:
            order_prep_time = (order.ready_at - order.created_at).total_seconds()
            OrderNotification.on_order_ready(order_id)

        items_status = [{
            'id': oi.id,
            'product_name': oi.product.name,
            'quantity': oi.quantity,
            'is_ready': oi.ready_at is not None,
            'ready_at': oi.ready_at.isoformat() if oi.ready_at else None,
            'preparation_time_seconds': (oi.ready_at - order.created_at).total_seconds() if oi.ready_at else None,
            'preparation_time_formatted': _format_duration((oi.ready_at - order.created_at).total_seconds()) if oi.ready_at else None,
        } for oi in order.items.all()]

        return ServiceResponse.success(
            data={
                'item': {
                    'id': item.id,
                    'product_name': item.product.name,
                    'ready_at': item.ready_at.isoformat(),
                    'preparation_time_seconds': item_prep_time,
                    'preparation_time_formatted': _format_duration(item_prep_time),
                },
                'order': {
                    'id': order.id,
                    'display_id': order.display_id,
                    'status': _to_api_status(order.status),
                    'all_items_ready': all_ready,
                    'ready_at': order.ready_at.isoformat() if order.ready_at else None,
                    'preparation_time_seconds': order_prep_time,
                    'preparation_time_formatted': _format_duration(order_prep_time) if order_prep_time else None,
                },
                'items_status': items_status,
            },
            message='Item marked as ready',
        )

    @staticmethod
    @transaction.atomic
    def unmark_item_ready(order_id, item_id, cashier_id=None, user_id=None, user_role=None):
        order = OrderRepository.get_by_id(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Cannot modify cancelled order')

        from base.models import OrderItem
        updated = OrderItem.objects.filter(
            id=item_id, order=order, ready_at__isnull=False
        ).update(ready_at=None)

        if not updated:
            return ServiceResponse.error('Item is not marked as ready')

        if order.status == 'READY':
            order.status = 'PREPARING'
            order.ready_at = None
            order.save(update_fields=['status', 'ready_at'])

        return ServiceResponse.success(
            data={'item_id': item_id, 'order_status': _to_api_status(order.status)},
            message='Item unmarked as ready',
        )

    @staticmethod
    @transaction.atomic
    def mark_as_paid(order_id, cashier_id, user_id=None, user_role=None,
                     payment_method='CASH', payments=None, discount_percent=0):
        """Mark an order paid. Two input shapes:

        - Legacy single: payment_method='CASH'  → one full-amount line.
        - Split: payments=[{'method','amount'}, ...] + optional discount_percent.

        Money rules: an optional percent discount cuts the bill to
        effective_total = round(total_amount * (1 - pct/100)); the payment lines
        must cover it; the only allowed overpayment is cash (the change). Only
        the cash share (net of change) hits the drawer; card/Payme settle
        externally.
        """
        from base.models import Order, OrderPayment
        # Lock the order row for the duration of payment processing to prevent
        # double-pay races (two concurrent requests both passing is_paid check).
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Cancelled order cannot be paid')

        if order.is_paid:
            return ServiceResponse.error('Order already paid')

        # MIXED is a roll-up marker the server sets — never an input method.
        valid_methods = [c[0] for c in Order.PaymentMethod.choices if c[0] != 'MIXED']

        # -- normalize discount + payment lines ---------------------------------
        try:
            pct = Decimal(str(discount_percent or 0))
        except Exception:  # noqa: BLE001
            return ServiceResponse.validation_error(errors={'discount_percent': 'Must be a number'})
        if pct < 0 or pct > 100:
            return ServiceResponse.validation_error(errors={'discount_percent': 'Must be 0..100'})

        base_total = Decimal(order.total_amount or 0)
        effective_total = (base_total * (Decimal('1') - pct / Decimal('100'))).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP)

        if payments:
            lines = []
            for p in payments:
                method = str((p or {}).get('method', '')).upper()
                if method not in valid_methods:
                    return ServiceResponse.validation_error(
                        errors={'payments': f'method must be one of {valid_methods}'})
                try:
                    amount = Decimal(str((p or {}).get('amount')))
                except Exception:  # noqa: BLE001
                    return ServiceResponse.validation_error(errors={'payments': 'amount must be a number'})
                if amount <= 0:
                    return ServiceResponse.validation_error(errors={'payments': 'amount must be > 0'})
                lines.append((method, amount))
        else:
            if payment_method not in valid_methods:
                return ServiceResponse.validation_error(
                    errors={'payment_method': f'Must be one of {valid_methods}'})
            lines = [(payment_method, effective_total)]

        paid_sum = sum((amt for _, amt in lines), Decimal('0'))
        cash_sum = sum((amt for m, amt in lines if m == 'CASH'), Decimal('0'))
        noncash_sum = paid_sum - cash_sum

        if paid_sum < effective_total:
            return ServiceResponse.validation_error(
                errors={'payments': 'Payments do not cover the total'},
                message=f'Short by {effective_total - paid_sum}')
        # Overpayment is only the customer's cash change. Non-cash must never
        # exceed the bill (no "overpay by card").
        if noncash_sum > effective_total:
            return ServiceResponse.validation_error(
                errors={'payments': 'Non-cash overpayment is not allowed'})

        # -- persist ------------------------------------------------------------
        distinct = {m for m, _ in lines}
        order.is_paid = True
        order.payment_method = (next(iter(distinct)) if len(distinct) == 1
                                else Order.PaymentMethod.MIXED)
        order.paid_at = timezone.now()

        # Credit the order to the cashier who collected the payment when it
        # isn't already attributed. In the restaurant flow a waiter (or the
        # customer) creates the order with cashier_id=NULL and the cashier only
        # rings up payment — without this the order stays unattributed and never
        # appears in that cashier's shift stats / cash reconciliation.
        cashier_fields = []
        if cashier_id and not order.cashier_id:
            order.cashier_id = cashier_id
            cashier_fields = ['cashier']

        if pct > 0:
            # Reflect the pay-time discount in the order totals (keeps the
            # invariant total_amount == subtotal - discount_amount).
            order.discount_percent = pct
            order.discount_amount = (Decimal(order.discount_amount or 0)
                                     + (base_total - effective_total))
            order.total_amount = effective_total
            order.save(update_fields=['is_paid', 'payment_method', 'paid_at',
                                      'discount_percent', 'discount_amount',
                                      'total_amount'] + cashier_fields)
        else:
            order.save(update_fields=['is_paid', 'payment_method', 'paid_at'] + cashier_fields)

        for method, amount in lines:
            OrderPayment.objects.create(order=order, method=method, amount=amount)

        # Cash drawer only tracks physical cash kept (net of change). The cash
        # share of the bill = effective_total - non-cash settled externally.
        cash_to_drawer = effective_total - noncash_sum
        if cash_to_drawer > 0:
            InkassaService.add_to_register(cash_to_drawer)
        OrderNotification.on_order_paid(order_id)

        # Fiscalize the sale (Soliq). No-op unless fiscalization is enabled.
        # serve-now: never blocks the sale on a provider error — a failure is
        # recorded and retried by the queue. Honors block-on-failure if set.
        _fiscalize_after_pay(order_id)

        try:
            from stock.services import OrderStatusHandler, StockSettingsService
            settings = StockSettingsService.load()
            if settings.stock_enabled and settings.deduct_on_order_status == 'PAID':
                location_id = StockSettingsService.get_default_location_id()
                if location_id:
                    stock_items = [
                        {'product_id': i.product_id, 'quantity': i.quantity}
                        for i in order.items.all()
                    ]
                    OrderStatusHandler.on_status_change(
                        order.id, order.status, 'PAID', stock_items, location_id, order.user_id,
                    )
        except Exception:
            logger.exception('non-critical stock-handler error in order flow')

        return ServiceResponse.success(
            data={'is_paid': True},
            message='Order marked as paid',
        )

    @staticmethod
    @transaction.atomic
    def mark_order_ready(order_id, cashier_id=None, user_id=None, user_role=None):
        # Row-lock the order so the status flip and the items bulk-update
        # run in the same transaction. Without atomic, a failure between
        # order.save() and items.update() would leave order=READY with
        # items still PREPARING — kitchen display contradicts the queue.
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_cashier_ownership(order, cashier_id, user_id=user_id, user_role=user_role)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Cannot mark cancelled order as ready')

        if order.status == 'READY':
            # Idempotent: the KDS may retry /ready on a flaky network. Return
            # 200 with the current state instead of an error, and skip the
            # side-effects (notification, ready_at re-stamp) so a retry can't
            # reset the prep timer or re-notify.
            order_prep_time = (
                (order.ready_at - order.created_at).total_seconds()
                if order.ready_at else None
            )
            return ServiceResponse.success(
                data={
                    'status': _to_api_status(order.status),
                    'ready_at': order.ready_at.isoformat() if order.ready_at else None,
                    'preparation_time_seconds': order_prep_time,
                    'preparation_time_formatted': _format_duration(order_prep_time),
                },
                message='Order already marked as ready',
            )

        now = timezone.now()
        order.status = 'READY'
        order.ready_at = now
        order.save(update_fields=['status', 'ready_at'])
        order.items.filter(ready_at__isnull=True).update(ready_at=now)

        order_prep_time = (order.ready_at - order.created_at).total_seconds()
        OrderNotification.on_order_ready(order_id)

        return ServiceResponse.success(
            data={
                'status': _to_api_status(order.status),
                'ready_at': order.ready_at.isoformat(),
                'preparation_time_seconds': order_prep_time,
                'preparation_time_formatted': _format_duration(order_prep_time),
            },
            message='Order marked as ready',
        )

    DISPLAY_LIMIT = 200

    @staticmethod
    def get_client_display_orders():
        from django.db.models import Count, Q
        five_minutes_ago = timezone.now() - timedelta(minutes=5)

        # Cap result counts so a busy day doesn't materialize thousands of rows
        # into the kitchen/lobby display response. Annotate item counts in SQL
        # — pre-fix each row issued two extra queries (items.count() and
        # items.filter().count()), defeating the prefetch and turning a
        # 200-row display into 600+ DB hits.
        processing = OrderRepository.model.objects.filter(
            status='PREPARING', is_deleted=False
        ).select_related('user').annotate(
            items_total=Count('items'),
            items_ready=Count('items', filter=Q(items__ready_at__isnull=False)),
        ).order_by('created_at')[:CustomerOrderService.DISPLAY_LIMIT]

        finished = OrderRepository.model.objects.filter(
            status='READY', is_deleted=False, ready_at__gte=five_minutes_ago
        ).select_related('user').order_by(
            '-ready_at'
        )[:CustomerOrderService.DISPLAY_LIMIT]

        processing_list = []
        for order in processing:
            total_items = order.items_total
            ready_items = order.items_ready
            processing_list.append({
                'id': order.id,
                'display_id': order.display_id,
                'user': f"{order.user.first_name} {order.user.last_name}",
                'total_amount': str(order.total_amount),
                'status': _to_api_status(order.status),
                'is_paid': order.is_paid,
                'items_ready': ready_items,
                'items_total': total_items,
                'progress_percent': round((ready_items / total_items * 100) if total_items > 0 else 0, 1),
                'created_at': order.created_at.isoformat(),
            })

        finished_list = []
        for order in finished:
            prep_time = (order.ready_at - order.created_at).total_seconds() if order.ready_at else None
            finished_list.append({
                'id': order.id,
                'display_id': order.display_id,
                'user': f"{order.user.first_name} {order.user.last_name}",
                'total_amount': str(order.total_amount),
                'is_paid': order.is_paid,
                'completed_at': order.ready_at.isoformat(),
                'preparation_time_seconds': prep_time,
                'preparation_time_formatted': _format_duration(prep_time) if prep_time else None,
            })

        return ServiceResponse.success(data={
            'processing': processing_list,
            'finished': finished_list,
        })

    @staticmethod
    def get_chef_display_orders():
        orders = OrderRepository.model.objects.filter(
            status='PREPARING', is_deleted=False
        ).select_related('user').prefetch_related('items__product').order_by(
            'created_at'
        )[:CustomerOrderService.DISPLAY_LIMIT]

        orders_list = []
        for order in orders:
            items = []
            ready_count = 0
            for item in order.items.all():
                # Instant items (drinks etc.) need no kitchen work — keep them
                # off the chef display entirely.
                if item.product.is_instant:
                    continue
                is_ready = item.ready_at is not None
                if is_ready:
                    ready_count += 1
                prep_time = (item.ready_at - order.created_at).total_seconds() if item.ready_at else None
                items.append({
                    'id': item.id,
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'detail': item.detail,
                    'is_ready': is_ready,
                    'ready_at': item.ready_at.isoformat() if item.ready_at else None,
                    'preparation_time_seconds': prep_time,
                    'preparation_time_formatted': _format_duration(prep_time) if prep_time else None,
                })

            total_items = len(items)
            # Nothing for the kitchen (all-instant order) — don't show it.
            if total_items == 0:
                continue
            orders_list.append({
                'id': order.id,
                'display_id': order.display_id,
                # The chef's kitchen number: monotonic (never wraps at 100) so the
                # line never sees the count reset. display_id stays for the
                # receipt/cashier short number.
                'chef_queue_number': order.chef_queue_number,
                'user': f"{order.user.first_name} {order.user.last_name}",
                'total_amount': str(order.total_amount),
                'is_paid': order.is_paid,
                'items': items,
                'items_ready': ready_count,
                'items_total': total_items,
                'progress_percent': round((ready_count / total_items * 100) if total_items > 0 else 0, 1),
                'created_at': order.created_at.isoformat(),
            })

        return ServiceResponse.success(data={'orders': orders_list})
