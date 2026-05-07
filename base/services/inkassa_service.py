from django.db import transaction
from django.db.models import F
from django.utils import timezone

from base.models import CashRegister
from base.repositories import CashRegisterRepository


class InkassaService:
    @staticmethod
    @transaction.atomic
    def add_to_register(amount):
        register = CashRegisterRepository.get_current()
        if not register:
            return
        # Atomic increment to avoid lost updates under concurrent payments.
        CashRegister.objects.filter(pk=register.pk).update(
            current_balance=F('current_balance') + amount,
            last_updated=timezone.now(),
        )

