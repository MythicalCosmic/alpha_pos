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
