"""Tests for the per-shift drawer + cashbox expenses (P1/P4)."""
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _user(email='cashier@t.local'):
    from base.models import User
    return User.objects.create(
        first_name='Cash', last_name='Ier', email=email, password='x',
        role='CASHIER', status='ACTIVE')


def _shift(user):
    from base.models import Shift
    return Shift.objects.create(user=user, start_time=timezone.now(), status='ACTIVE')


def _paid_cash_order(user, amount, method='CASH'):
    from base.models import Order, OrderPayment
    o = Order.objects.create(
        user=user, cashier=user, status='COMPLETED', is_paid=True,
        paid_at=timezone.now(), total_amount=amount, payment_method=method)
    OrderPayment.objects.create(order=o, method=method, amount=amount)
    return o


class TestDrawer:
    def test_drawer_cash_from_payments(self):
        from cashbox.services.drawer import drawer_cash, expected_payment_totals
        u = _user(); s = _shift(u)
        _paid_cash_order(u, Decimal('100000'), 'CASH')
        _paid_cash_order(u, Decimal('40000'), 'UZCARD')
        assert drawer_cash(s) == Decimal('100000.00')
        totals = expected_payment_totals(s)
        assert totals['CASH'] == Decimal('100000.00')
        assert totals['UZCARD'] == Decimal('40000.00')

    def test_cash_expense_reduces_drawer(self):
        from cashbox.services.drawer import drawer_cash
        from cashbox.services.expense_service import CashboxExpenseService
        u = _user(); s = _shift(u)
        _paid_cash_order(u, Decimal('100000'), 'CASH')
        res, st = CashboxExpenseService.create(
            s.id, Decimal('30000'), comment='napkins', created_by=u)
        assert st == 201, res
        assert drawer_cash(s) == Decimal('70000.00')


class TestCashboxExpenseRecipients:
    def test_supplier_recipient_reduces_supplier_balance(self):
        from stock.models import Supplier
        from cashbox.services.expense_service import CashboxExpenseService
        u = _user(); s = _shift(u)
        sup = Supplier.objects.create(name='Veg Co', current_balance=Decimal('50000'))
        res, st = CashboxExpenseService.create(
            s.id, Decimal('20000'), recipient_supplier_id=sup.id, created_by=u)
        assert st == 201, res
        sup.refresh_from_db()
        assert sup.current_balance == Decimal('30000.00')

    def test_two_recipients_rejected(self):
        from base.models import User
        from stock.models import Supplier
        from cashbox.services.expense_service import CashboxExpenseService
        u = _user(); s = _shift(u)
        other = User.objects.create(first_name='A', last_name='B',
                                    email='a@t.local', password='x', role='CASHIER')
        sup = Supplier.objects.create(name='Veg Co')
        res, st = CashboxExpenseService.create(
            s.id, Decimal('1000'), recipient_user_id=other.id,
            recipient_supplier_id=sup.id, created_by=u)
        assert st >= 400


class TestShiftSettlement:
    def test_close_and_confirm_posts_to_treasury(self):
        from base.models import TreasuryAccount
        from admins.services.shift_service import ShiftService
        from cashbox.models import ShiftPaymentTotal
        u = _user(); s = _shift(u)
        _paid_cash_order(u, Decimal('100000'), 'CASH')
        _paid_cash_order(u, Decimal('40000'), 'UZCARD')
        res, st = ShiftService.end_shift(
            s.id, u.id, '', actor=u,
            counted={'CASH': '100000', 'UZCARD': '40000'})
        assert st == 200, res
        s.refresh_from_db()
        assert s.status == 'ENDED'
        cash_spt = ShiftPaymentTotal.objects.get(shift=s, method='CASH')
        assert cash_spt.expected_amount == Decimal('100000.00')
        assert cash_spt.counted_amount == Decimal('100000.00')
        assert cash_spt.difference == Decimal('0.00')

        res, st = ShiftService.reconcile(
            s.id, actual_cash='100000', notes='', reconciled_by_id=u.id,
            confirmed={'CASH': '100000', 'UZCARD': '40000'})
        assert st == 201, res
        s.refresh_from_db()
        assert s.status == 'COMPLETED'
        assert TreasuryAccount.objects.get(kind='SAFE').balance == Decimal('100000.00')
        assert TreasuryAccount.objects.get(kind='BANK').balance == Decimal('40000.00')

    def test_ensure_active_shift_idempotent(self):
        from admins.services.shift_service import ShiftService
        from base.models import Shift
        u = _user()
        a = ShiftService.ensure_active_shift(u.id)
        b = ShiftService.ensure_active_shift(u.id)
        assert a.id == b.id
        assert Shift.objects.filter(user=u, status='ACTIVE').count() == 1
