from base.repositories import CashRegisterRepository


class InkassaService:
    @staticmethod
    def add_to_register(amount):
        register = CashRegisterRepository.get_current()
        if not register:
            return
        register.current_balance += amount
        register.save(update_fields=['current_balance', 'last_updated'])

