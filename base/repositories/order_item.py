from django.db.models import Sum, F, Count, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from base.repositories.base import BaseSyncRepository
from base.models import OrderItem


class OrderItemRepository(BaseSyncRepository):
    model = OrderItem

    @classmethod
    def get_by_order(cls, order):
        return cls.model.objects.filter(is_deleted=False, order=order)

    @classmethod
    def get_by_order_id(cls, order_id):
        return cls.model.objects.filter(is_deleted=False, order_id=order_id)

    @classmethod
    def get_by_product(cls, product):
        return cls.model.objects.filter(is_deleted=False, product=product)

    @classmethod
    def get_by_order_with_product(cls, order_id):
        return cls.model.objects.filter(
            is_deleted=False, order_id=order_id
        ).select_related('product__category')

    @classmethod
    def get_unready_by_order(cls, order_id):
        return cls.model.objects.filter(
            is_deleted=False, order_id=order_id, ready_at__isnull=True
        )

    @classmethod
    def get_existing_unready(cls, order_id, product_id):
        return cls.model.objects.filter(
            order_id=order_id, product_id=product_id, ready_at__isnull=True
        ).first()

    @classmethod
    def calculate_order_total(cls, order):
        return order.items.aggregate(
            total=Coalesce(
                Sum(F('price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2)),
                Decimal('0.00')
            )
        )['total']

    @classmethod
    def get_top_products(cls, date_from=None, date_to=None, limit=20):
        qs = cls.model.objects.filter(is_deleted=False, order__is_deleted=False)
        if date_from:
            qs = qs.filter(order__created_at__gte=date_from)
        if date_to:
            qs = qs.filter(order__created_at__lte=date_to)

        return list(qs.values(
            'product_id', 'product__name', 'product__category__name'
        ).annotate(
            total_qty=Sum('quantity'),
            total_revenue=Coalesce(
                Sum(F('price') * F('quantity'), output_field=DecimalField()),
                Decimal('0.00')
            ),
            order_count=Count('order_id', distinct=True),
        ).order_by('-total_qty')[:limit])

    @classmethod
    def get_least_sold_products(cls, date_from=None, date_to=None, limit=20):
        qs = cls.model.objects.filter(is_deleted=False, order__is_deleted=False)
        if date_from:
            qs = qs.filter(order__created_at__gte=date_from)
        if date_to:
            qs = qs.filter(order__created_at__lte=date_to)

        return list(qs.values(
            'product_id', 'product__name', 'product__category__name'
        ).annotate(
            total_qty=Sum('quantity'),
            total_revenue=Coalesce(
                Sum(F('price') * F('quantity'), output_field=DecimalField()),
                Decimal('0.00')
            ),
            order_count=Count('order_id', distinct=True),
        ).order_by('total_qty')[:limit])

    @classmethod
    def get_product_category_stats(cls, date_from=None, date_to=None):
        qs = cls.model.objects.filter(is_deleted=False, order__is_deleted=False)
        if date_from:
            qs = qs.filter(order__created_at__gte=date_from)
        if date_to:
            qs = qs.filter(order__created_at__lte=date_to)

        return list(qs.values(
            'product__category_id', 'product__category__name'
        ).annotate(
            total_qty=Sum('quantity'),
            total_revenue=Coalesce(
                Sum(F('price') * F('quantity'), output_field=DecimalField()),
                Decimal('0.00')
            ),
            order_count=Count('order_id', distinct=True),
        ).order_by('-total_revenue'))
