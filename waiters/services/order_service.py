import logging

logger = logging.getLogger(__name__)
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from base.repositories import (
    OrderRepository, OrderItemRepository, ProductRepository,
    UserRepository, PlaceRepository, TableRepository,
)
from base.helpers.response import ServiceResponse
from notifications.handlers.order import OrderNotification
from base.models import Table


def _serialize_order_list(order):
    return {
        'id': order.id,
        'display_id': order.display_id,
        'order_type': order.order_type,
        'phone_number': order.phone_number,
        'description': order.description,
        'place': {
            'id': order.place.id,
            'name': order.place.name,
        } if order.place else None,
        'table': {
            'id': order.table.id,
            'number': order.table.number,
        } if order.table else None,
        'status': order.status,
        'is_paid': order.is_paid,
        'total_amount': str(order.total_amount or 0),
        # The list queryset is prefetched with `items__product__category`
        # (OrderRepository.get_with_relations) — iterate the cached items
        # instead of `.count()` (extra query per order) and `.values()` (fresh
        # query that bypasses the prefetch). Mirrors the admin list serializer.
        'items_count': len(order.items.all()),
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
        'created_at': order.created_at.isoformat(),
        'updated_at': order.updated_at.isoformat(),
    }


def _serialize_order_detail(order):
    items = []
    for item in order.items.all():
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
        })

    return {
        'id': order.id,
        'display_id': order.display_id,
        'order_type': order.order_type,
        'phone_number': order.phone_number,
        'description': order.description,
        'place': {
            'id': order.place.id,
            'name': order.place.name,
        } if order.place else None,
        'table': {
            'id': order.table.id,
            'number': order.table.number,
        } if order.table else None,
        'cashier': {
            'id': order.cashier.id,
            'name': f"{order.cashier.first_name} {order.cashier.last_name}"
        } if order.cashier else None,
        'status': order.status,
        'is_paid': order.is_paid,
        'total_amount': str(order.total_amount),
        'items': items,
        'items_ready_count': sum(1 for i in items if i['is_ready']),
        'items_total_count': len(items),
        'created_at': order.created_at.isoformat(),
        'updated_at': order.updated_at.isoformat(),
        'ready_at': order.ready_at.isoformat() if order.ready_at else None,
    }


def _check_waiter_ownership(order, waiter_user_id):
    if order.cashier_id != waiter_user_id:
        return ServiceResponse.forbidden(
            f'You do not have permission to modify this order. Order #{order.display_id} belongs to another waiter.'
        )
    return None


def _recalculate_total(order):
    order.subtotal = OrderItemRepository.calculate_order_total(order)
    order.total_amount = order.subtotal - order.discount_amount
    order.save(update_fields=['subtotal', 'total_amount'])


class WaiterOrderService:

    @staticmethod
    def list_my_orders(waiter_user_id, page=1, per_page=20, status=None):
        qs = OrderRepository.build_filtered_queryset(
            cashier_id=waiter_user_id,
            statuses=status if isinstance(status, list) else ([status] if status else None),
            order_by='-created_at',
        )

        page_obj, paginator = OrderRepository.paginate(qs, page, per_page)
        orders = [_serialize_order_list(o) for o in page_obj.object_list]

        return ServiceResponse.success(data={
            'orders': orders,
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
    @transaction.atomic
    def create_order(user_id, items, place_id=None, table_id=None,
                     order_type='HALL', phone_number=None, description=None):
        if not UserRepository.exists(id=user_id, role='WAITER'):
            return ServiceResponse.not_found('Waiter not found')

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

        place = None
        table = None

        if place_id:
            place = PlaceRepository.get_by_id(place_id)
            if not place:
                return ServiceResponse.not_found('Place not found')

        if table_id:
            table = TableRepository.get_by_id(table_id)
            if not table:
                return ServiceResponse.not_found('Table not found')
            if place and table.place_id != place.id:
                return ServiceResponse.error('Table does not belong to the specified place')
            if not place:
                place = table.place

        display_id = OrderRepository.next_display_id()

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
            cashier_id=user_id,
            display_id=display_id,
            order_type=order_type,
            phone_number=phone_number,
            description=description,
            status='PREPARING',
            is_paid=False,
            subtotal=total_amount,
            total_amount=total_amount,
            place=place,
            table=table,
        )

        from base.models import OrderItem
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=d['product'],
                detail=d['detail'],
                quantity=d['quantity'],
                price=d['price'],
                ready_at=None,
            ) for d in order_items_data
        ])

        if table:
            TableRepository.update_status(table.id, Table.Status.OCCUPIED)

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
            logger.exception('non-critical stock-handler error in waiter order flow')

        return ServiceResponse.created(
            data={'order_id': order.id, 'display_id': order.display_id},
            message='Order created successfully',
        )

    @staticmethod
    def get_order(order_id, waiter_user_id):
        order = OrderRepository.get_by_id_with_relations(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
        if ownership:
            return ownership

        return ServiceResponse.success(data={'order': _serialize_order_detail(order)})

    @staticmethod
    @transaction.atomic
    def add_item(order_id, product_id, quantity, waiter_user_id):
        # Row-lock the order so concurrent add-item calls serialize across
        # both the quantity increment and the subtotal recalculate.
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
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

        if quantity <= 0:
            return ServiceResponse.validation_error(
                errors={'quantity': 'Must be greater than 0'},
                message='Quantity must be greater than 0',
            )

        existing = OrderItemRepository.get_existing_unready(order_id, product_id)
        if existing:
            # Increment in SQL so concurrent add-item calls cannot lose updates.
            from django.db.models import F
            OrderItemRepository.model.objects.filter(pk=existing.pk).update(
                quantity=F('quantity') + quantity,
            )
        else:
            OrderItemRepository.create(
                order=order, product=product, quantity=quantity, price=product.price
            )

        if order.ready_at:
            order.ready_at = None
            order.status = 'PREPARING'
            order.save(update_fields=['ready_at', 'status'])

        _recalculate_total(order)
        return ServiceResponse.success(message='Item added to order successfully')

    @staticmethod
    @transaction.atomic
    def update_item(order_id, item_id, quantity, waiter_user_id):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
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

        item.quantity = quantity
        item.save(update_fields=['quantity'])
        _recalculate_total(order)

        return ServiceResponse.success(message='Order item updated successfully')

    @staticmethod
    @transaction.atomic
    def remove_item(order_id, item_id, waiter_user_id):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
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

        item.delete(hard_delete=True)

        if not order.items.exists():
            if order.table:
                TableRepository.update_status(order.table_id, Table.Status.AVAILABLE)
            order.delete(hard_delete=True)
            return ServiceResponse.success(message='Order deleted (no items remaining)')

        _recalculate_total(order)
        return ServiceResponse.success(message='Item removed from order successfully')

    @staticmethod
    def mark_ready(order_id, waiter_user_id):
        order = OrderRepository.get_by_id(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Cannot mark cancelled order as ready')

        if order.status == 'READY':
            return ServiceResponse.error('Order is already ready')

        now = timezone.now()
        order.status = 'READY'
        order.ready_at = now
        order.save(update_fields=['status', 'ready_at'])
        order.items.filter(ready_at__isnull=True).update(ready_at=now)

        OrderNotification.on_order_ready(order_id)

        return ServiceResponse.success(
            data={'status': order.status, 'ready_at': order.ready_at.isoformat()},
            message='Order marked as ready',
        )

    @staticmethod
    @transaction.atomic
    def cancel_order(order_id, waiter_user_id):
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found('Order not found')

        ownership = _check_waiter_ownership(order, waiter_user_id)
        if ownership:
            return ownership

        if order.status == 'CANCELED':
            return ServiceResponse.error('Order is already cancelled')

        old_status = order.status
        order.status = 'CANCELED'
        order.save(update_fields=['status'])

        # Cancelling a paid order must reverse the cash-register entry.
        # Only cash reverses through the drawer; card/Payme settle externally.
        if (
            order.is_paid
            and order.total_amount
            and (order.payment_method == 'CASH' or order.payment_method is None)
        ):
            from base.services.inkassa_service import InkassaService
            InkassaService.add_to_register(-order.total_amount)

        if order.table:
            TableRepository.update_status(order.table_id, Table.Status.AVAILABLE)

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
                    order.id, old_status, 'CANCELED', stock_items, location_id, order.user_id,
                )
        except Exception:
            logger.exception('non-critical stock-handler error in waiter order flow')

        return ServiceResponse.success(
            data={'status': 'CANCELED'},
            message='Order cancelled successfully',
        )

    @staticmethod
    def list_places():
        places = PlaceRepository.get_active()
        data = [
            {
                'id': p.id,
                'name': p.name,
                'place_type': p.place_type,
                'capacity': p.capacity,
                'tables_count': p.tables.filter(is_deleted=False).count(),
            }
            for p in places
        ]
        return ServiceResponse.success(data={'places': data})

    @staticmethod
    def list_tables(place_id=None):
        if place_id:
            tables = TableRepository.get_for_place(place_id)
        else:
            tables = TableRepository.get_active()

        data = [
            {
                'id': t.id,
                'number': t.number,
                'capacity': t.capacity,
                'status': t.status,
                'is_active': t.is_active,
                'place': {
                    'id': t.place.id,
                    'name': t.place.name,
                } if t.place else None,
            }
            for t in tables.select_related('place')
        ]
        return ServiceResponse.success(data={'tables': data})

    @staticmethod
    def update_table_status(table_id, status, actor_user_id=None, actor_role=None):
        valid_statuses = [c[0] for c in Table.Status.choices]
        if status not in valid_statuses:
            return ServiceResponse.validation_error(
                errors={'status': f'Must be one of: {", ".join(valid_statuses)}'},
                message='Invalid table status',
            )

        # Non-admin waiters can only flip a table they're actively serving.
        # Without this check WAITER A could re-flag any table in any branch.
        # An admin can transition any table (cleanup / closeout flows).
        if actor_role and actor_role != 'ADMIN':
            from base.repositories import OrderRepository
            has_active_order = OrderRepository.model.objects.filter(
                is_deleted=False,
                table_id=table_id,
                cashier_id=actor_user_id,
                status__in=('PREPARING', 'READY'),
            ).exists()
            if not has_active_order:
                return ServiceResponse.forbidden(
                    'You can only update the status of a table you are serving',
                )

        table = TableRepository.update_status(table_id, status)
        if not table:
            return ServiceResponse.not_found('Table not found')

        return ServiceResponse.success(
            data={
                'id': table.id,
                'number': table.number,
                'status': table.status,
            },
            message='Table status updated',
        )
