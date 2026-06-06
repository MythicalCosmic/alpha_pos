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
