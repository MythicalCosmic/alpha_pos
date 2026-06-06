"""Regression tests for admin user/inkassa bugs."""
from decimal import Decimal

import pytest

from admins.services.user_service import AdminUserService
from admins.services.inkassa_service import AdminInkassaService

pytestmark = pytest.mark.django_db


class TestUserRoleValidation:
    """Pre-fix: update_user accepted any string for role, allowing
    role='SUPERADMIN' or other invalid privilege escalation."""

    def test_invalid_role_rejected_on_update(self, regular_user):
        result, status = AdminUserService.update_user(
            regular_user.id, role='SUPERADMIN',
        )
        assert status == 422
        assert 'role' in result.get('errors', {})

    def test_valid_role_accepted_on_update(self, regular_user):
        result, status = AdminUserService.update_user(
            regular_user.id, role='CASHIER',
        )
        assert status == 200
        regular_user.refresh_from_db()
        assert regular_user.role == 'CASHIER'

    def test_invalid_status_rejected_on_update(self, regular_user):
        result, status = AdminUserService.update_user(
            regular_user.id, status='DELETED_SOFT',
        )
        assert status == 422
        assert 'status' in result.get('errors', {})

    def test_invalid_role_rejected_on_create(self):
        # Valid 4-digit PIN so the role check is what trips the rejection.
        result, status = AdminUserService.create_user(
            first_name='X', last_name='Y',
            role='ROOT', password='1234', email='x@y.local',
        )
        assert status == 422

    def test_non_pin_password_rejected_on_create(self):
        # Staff sign in with a 4-digit PIN: anything that isn't exactly
        # 4 digits (too short, too long, non-numeric) is rejected.
        for bad in ('abc', '123', '12345', '12a4'):
            result, status = AdminUserService.create_user(
                first_name='X', last_name='Y',
                role='CASHIER', password=bad, email='x@y.local',
            )
            assert status == 422
            assert 'password' in result.get('errors', {})

    def test_four_digit_pin_accepted_on_create(self):
        result, status = AdminUserService.create_user(
            first_name='Pin', last_name='User',
            role='CASHIER', password='4821', email='pin@y.local',
        )
        assert status == 201


class TestInkassaFloor:
    """Pre-fix: cashier could withdraw more than the register held, driving
    current_balance negative."""

    def test_withdrawal_exceeding_balance_rejected(self, admin_user):
        from base.models import CashRegister
        CashRegister.objects.create(current_balance=Decimal('100'))

        result, status = AdminInkassaService.perform(
            admin_user, {'cash': '500'},
        )
        assert status == 422
        register = CashRegister.objects.first()
        assert register.current_balance == Decimal('100')

    def test_negative_amount_rejected(self, admin_user):
        from base.models import CashRegister
        CashRegister.objects.create(current_balance=Decimal('100'))

        result, status = AdminInkassaService.perform(
            admin_user, {'cash': '-50'},
        )
        assert status == 422

    def test_valid_withdrawal_succeeds(self, admin_user):
        from base.models import CashRegister
        CashRegister.objects.create(current_balance=Decimal('1000'))

        result, status = AdminInkassaService.perform(
            admin_user, {'cash': '300'},
        )
        assert status == 200
        register = CashRegister.objects.first()
        assert register.current_balance == Decimal('700')


class TestInkassaTreasuryRouting:
    """Inkassa: only cash leaves the register; cash -> SAFE, cards -> BANK."""

    def test_cash_to_safe_card_to_bank(self, admin_user):
        from base.models import CashRegister, TreasuryAccount
        CashRegister.objects.create(current_balance=Decimal('1000'))
        result, status = AdminInkassaService.perform(
            admin_user, {'cash': '400', 'uzcard': '300', 'humo': '100'})
        assert status == 200
        # Only the 400 cash left the drawer (bug fix: cards never were in it).
        assert CashRegister.objects.first().current_balance == Decimal('600')
        assert TreasuryAccount.objects.get(kind='SAFE').balance == Decimal('400')
        assert TreasuryAccount.objects.get(kind='BANK').balance == Decimal('400')
        assert Decimal(result['data']['cash_to_safe']) == Decimal('400')
        assert Decimal(result['data']['card_to_bank']) == Decimal('400')

    def test_card_only_inkassa_ignores_empty_register(self, admin_user):
        from base.models import CashRegister, TreasuryAccount
        CashRegister.objects.create(current_balance=Decimal('0'))
        result, status = AdminInkassaService.perform(admin_user, {'payme': '500'})
        assert status == 200  # card inkassa not bounded by cash drawer
        assert CashRegister.objects.first().current_balance == Decimal('0')
        assert TreasuryAccount.objects.get(kind='BANK').balance == Decimal('500')


class TestTreasury:
    def test_transfer_bank_to_safe_with_fee(self, admin_user):
        from base.models import TreasuryAccount
        from base.services.treasury_service import TreasuryService
        TreasuryAccount.objects.create(kind='BANK', balance=Decimal('1000'))
        TreasuryAccount.objects.create(kind='SAFE', balance=Decimal('0'))
        res, st = TreasuryService.transfer('BANK', 'SAFE', '1000', fee='5', performed_by=admin_user)
        assert st == 200
        assert TreasuryAccount.objects.get(kind='BANK').balance == Decimal('0')
        assert TreasuryAccount.objects.get(kind='SAFE').balance == Decimal('995')

    def test_transfer_insufficient_rejected(self, admin_user):
        from base.models import TreasuryAccount
        from base.services.treasury_service import TreasuryService
        TreasuryAccount.objects.create(kind='SAFE', balance=Decimal('100'))
        _, st = TreasuryService.transfer('SAFE', 'BANK', '500', performed_by=admin_user)
        assert st == 422

    def test_expense_from_safe(self, admin_user):
        from base.models import TreasuryAccount
        from base.services.treasury_service import TreasuryService
        TreasuryAccount.objects.create(kind='SAFE', balance=Decimal('300'))
        res, st = TreasuryService.record_expense('SAFE', '120', category='supplies', performed_by=admin_user)
        assert st == 201
        assert TreasuryAccount.objects.get(kind='SAFE').balance == Decimal('180')

    def test_expense_insufficient_rejected(self, admin_user):
        from base.models import TreasuryAccount
        from base.services.treasury_service import TreasuryService
        TreasuryAccount.objects.create(kind='BANK', balance=Decimal('50'))
        _, st = TreasuryService.record_expense('BANK', '100', performed_by=admin_user)
        assert st == 422


class TestShiftHandoverReport:
    def test_report_smoke(self, cashier_user):
        from datetime import timedelta
        from django.utils import timezone
        from base.models import Shift
        from admins.services.shift_analytics_service import shift_handover_report
        s = Shift.objects.create(
            user=cashier_user, start_time=timezone.now() - timedelta(hours=2),
            status='ACTIVE')
        rep = shift_handover_report(s)
        assert set(['shift', 'receipts', 'products', 'distribution', 'peak_hour']) <= set(rep)
        assert rep['receipt_count'] == 0
        assert 'cash' in rep['shift']['money'] and 'card' in rep['shift']['money']
