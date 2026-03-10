from base.repositories.base import BaseSyncRepository
from base.models import Inkassa


class InkassaRepository(BaseSyncRepository):
    model = Inkassa

    @classmethod
    def get_by_cashier(cls, cashier):
        return cls.model.objects.filter(is_deleted=False, cashier=cashier)

    @classmethod
    def get_by_type(cls, inkass_type):
        return cls.model.objects.filter(is_deleted=False, inkass_type=inkass_type)

    @classmethod
    def get_latest(cls):
        return cls.model.objects.filter(is_deleted=False).order_by('-created_at').first()
