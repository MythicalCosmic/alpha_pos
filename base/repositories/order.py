from base.repositories.base import BaseSyncRepository
from base.models import Order


class OrderRepository(BaseSyncRepository):
    model = Order

    @classmethod
    def get_by_status(cls, status):
        return cls.model.objects.filter(is_deleted=False, status=status)

    @classmethod
    def get_by_user(cls, user):
        return cls.model.objects.filter(is_deleted=False, user=user)

    @classmethod
    def get_by_display_id(cls, display_id):
        try:
            return cls.model.objects.get(display_id=display_id, is_deleted=False)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_order_type(cls, order_type):
        return cls.model.objects.filter(is_deleted=False, order_type=order_type)

    @classmethod
    def get_open(cls):
        return cls.model.objects.filter(
            is_deleted=False,
            status__in=[Order.Status.OPEN, Order.Status.PREPARING, Order.Status.READY],
        )

    @classmethod
    def get_completed(cls):
        return cls.model.objects.filter(is_deleted=False, status=Order.Status.COMPLETED)

    @classmethod
    def get_unpaid(cls):
        return cls.model.objects.filter(is_deleted=False, is_paid=False).exclude(
            status=Order.Status.CANCELED,
        )

    @classmethod
    def get_by_cashier(cls, cashier):
        return cls.model.objects.filter(is_deleted=False, cashier=cashier)

    @classmethod
    def get_by_delivery_person(cls, delivery_person):
        return cls.model.objects.filter(is_deleted=False, delivery_person=delivery_person)
