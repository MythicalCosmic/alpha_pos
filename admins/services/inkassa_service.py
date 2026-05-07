import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Count, F
from django.utils import timezone

from base.models import CashRegister, Inkassa, Order, OrderItem
from base.helpers.response import ServiceResponse

logger = logging.getLogger(__name__)


class AdminInkassaService:

    @staticmethod
    def get_balance():
        register, _ = CashRegister.objects.get_or_create(
            is_deleted=False, defaults={'current_balance': 0}
        )
        return ServiceResponse.success(data={
            'balance': float(register.current_balance),
            'last_updated': register.last_updated.isoformat(),
        })

    @staticmethod
    def get_stats():
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_orders = Order.objects.filter(
            is_deleted=False, paid_at__gte=today_start,
        )
        today_agg = today_orders.aggregate(
            total_revenue=Sum('total_amount'),
            order_count=Count('id'),
        )

        cashier_perf = (
            Order.objects.filter(is_deleted=False, paid_at__gte=today_start)
            .values('cashier__id', 'cashier__first_name', 'cashier__last_name')
            .annotate(
                total_revenue=Sum('total_amount'),
                order_count=Count('id'),
            )
            .order_by('-total_revenue')
        )

        top_products = (
            OrderItem.objects.filter(
                order__is_deleted=False,
                order__paid_at__gte=today_start,
                is_deleted=False,
            )
            .values('product__id', 'product__name')
            .annotate(
                total_quantity=Sum('quantity'),
                total_revenue=Sum(F('price') * F('quantity')),
            )
            .order_by('-total_quantity')[:10]
        )

        return ServiceResponse.success(data={
            'stats': {
                'today': {
                    'total_revenue': float(today_agg['total_revenue'] or 0),
                    'order_count': today_agg['order_count'] or 0,
                },
                'cashier_performance': [
                    {
                        'cashier_id': cp['cashier__id'],
                        'cashier_name': f"{cp['cashier__first_name'] or ''} {cp['cashier__last_name'] or ''}".strip(),
                        'total_revenue': float(cp['total_revenue'] or 0),
                        'order_count': cp['order_count'],
                    }
                    for cp in cashier_perf
                ],
                'top_products': [
                    {
                        'product_id': tp['product__id'],
                        'product_name': tp['product__name'],
                        'total_quantity': tp['total_quantity'],
                        'total_revenue': float(tp['total_revenue'] or 0),
                    }
                    for tp in top_products
                ],
            }
        })

    @staticmethod
    def get_history(page=1, per_page=20):
        qs = Inkassa.objects.filter(is_deleted=False).select_related('cashier').order_by('-created_at')
        total = qs.count()
        total_pages = (total + per_page - 1) // per_page
        items = qs[(page - 1) * per_page: page * per_page]

        return ServiceResponse.success(data={
            'inkassas': [_serialize_inkassa(i) for i in items],
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_inkassas': total,
                'total_pages': total_pages,
                'has_next': page * per_page < total,
                'has_previous': page > 1,
            },
        })

    @staticmethod
    def get_detail(inkassa_id):
        try:
            inkassa = Inkassa.objects.select_related('cashier').get(
                pk=inkassa_id, is_deleted=False
            )
        except Inkassa.DoesNotExist:
            return ServiceResponse.not_found('Inkassa not found')
        return ServiceResponse.success(data={'inkassa': _serialize_inkassa(inkassa)})

    @staticmethod
    @transaction.atomic
    def perform(user, amounts):
        register = CashRegister.objects.select_for_update().filter(is_deleted=False).first()
        if not register:
            register = CashRegister.objects.create(current_balance=0)

        balance_before = register.current_balance

        method_amounts = {}
        total_removed = Decimal('0')
        for method in ('CASH', 'UZCARD', 'HUMO', 'PAYME'):
            amount = amounts.get(method.lower(), 0)
            try:
                amount = Decimal(str(amount))
            except Exception:
                amount = Decimal('0')
            if amount < 0:
                return ServiceResponse.validation_error(
                    errors={method.lower(): 'Amount cannot be negative'},
                    message='Invalid amount',
                )
            if amount > 0:
                method_amounts[method] = amount
                total_removed += amount

        if total_removed <= 0:
            return ServiceResponse.validation_error(
                errors={'amount': 'At least one payment method amount must be greater than 0'},
                message='No amounts provided',
            )

        if total_removed > balance_before:
            return ServiceResponse.validation_error(
                errors={'amount': f'Total {total_removed} exceeds register balance {balance_before}'},
                message='Insufficient register balance',
            )

        last_inkassa = Inkassa.objects.filter(is_deleted=False).order_by('-created_at').first()
        period_start = last_inkassa.period_end if last_inkassa else None

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_orders = Order.objects.filter(
            is_deleted=False, paid_at__gte=period_start or today_start,
        )
        today_agg = today_orders.aggregate(
            total_revenue=Sum('total_amount'),
            order_count=Count('id'),
        )

        created_inkassas = []
        running_removed = Decimal('0')
        for method, amount in method_amounts.items():
            inkassa = Inkassa.objects.create(
                cashier=user,
                amount=amount,
                inkass_type=method,
                balance_before=balance_before,
                balance_after=balance_before - running_removed - amount,
                period_start=period_start,
                total_orders=today_agg['order_count'] or 0,
                total_revenue=today_agg['total_revenue'] or 0,
                notes=amounts.get('notes', ''),
            )
            running_removed += amount
            created_inkassas.append(inkassa)

        register.current_balance -= total_removed
        register.save(update_fields=['current_balance', 'last_updated'])

        return ServiceResponse.success(
            data={
                'amount_removed': float(total_removed),
                'balance_before': float(balance_before),
                'balance_after': float(register.current_balance),
                'inkassas': [_serialize_inkassa(i) for i in created_inkassas],
            },
            message='Inkassa performed successfully',
        )


def _serialize_inkassa(i):
    return {
        'id': i.id,
        'amount': float(i.amount),
        'inkass_type': i.inkass_type,
        'balance_before': float(i.balance_before),
        'balance_after': float(i.balance_after),
        'period_start': i.period_start.isoformat() if i.period_start else None,
        'period_end': i.period_end.isoformat() if i.period_end else None,
        'total_orders': i.total_orders,
        'total_revenue': float(i.total_revenue),
        'notes': i.notes or '',
        'cashier': {
            'id': i.cashier.id,
            'name': f"{i.cashier.first_name} {i.cashier.last_name}",
        } if i.cashier else None,
        'created_at': i.created_at.isoformat(),
    }
