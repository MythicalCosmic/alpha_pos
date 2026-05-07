"""Regression tests for the order/auth bugs we fixed in the security review."""
import pytest

from customers.services.order_service import (
    CustomerOrderService, _check_cashier_ownership,
)


pytestmark = pytest.mark.django_db


class TestCashierOwnershipIDOR:
    """Pre-fix: any logged-in USER could mutate any order whose cashier_id
    was None, including marking it paid. The role-aware check must reject."""

    def test_user_cannot_modify_other_users_order(self, order_factory, regular_user, other_user):
        order = order_factory(user=regular_user)
        result = _check_cashier_ownership(
            order, cashier_id=None, user_id=other_user.id, user_role='USER',
        )
        assert result is not None, 'expected forbidden when USER targets others order'

    def test_user_can_modify_own_order(self, order_factory, regular_user):
        order = order_factory(user=regular_user)
        result = _check_cashier_ownership(
            order, cashier_id=None, user_id=regular_user.id, user_role='USER',
        )
        assert result is None

    def test_cashier_blocked_when_other_cashier_owns_order(
        self, order_factory, cashier_user, other_cashier_user, regular_user,
    ):
        order = order_factory(user=regular_user, cashier=other_cashier_user)
        result = _check_cashier_ownership(
            order, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert result is not None

    def test_cashier_can_claim_unowned_order(
        self, order_factory, cashier_user, regular_user,
    ):
        order = order_factory(user=regular_user, cashier=None)
        result = _check_cashier_ownership(
            order, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert result is None

    def test_admin_bypass(self, order_factory, admin_user, regular_user):
        order = order_factory(user=regular_user)
        result = _check_cashier_ownership(
            order, cashier_id=None, user_id=admin_user.id, user_role='ADMIN',
        )
        assert result is None


class TestGetOrderReadIDOR:
    """get_order_by_id must enforce user-level ownership for non-admin/cashier."""

    def test_user_cannot_read_other_users_order(
        self, order_factory, regular_user, other_user,
    ):
        order = order_factory(user=regular_user)
        result, status = CustomerOrderService.get_order_by_id(
            order.id, user_id=other_user.id, user_role='USER',
        )
        assert status == 403

    def test_user_can_read_own_order(self, order_factory, regular_user):
        order = order_factory(user=regular_user)
        result, status = CustomerOrderService.get_order_by_id(
            order.id, user_id=regular_user.id, user_role='USER',
        )
        assert status == 200

    def test_cashier_can_read_any_order(
        self, order_factory, regular_user, cashier_user,
    ):
        order = order_factory(user=regular_user)
        result, status = CustomerOrderService.get_order_by_id(
            order.id, user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 200


class TestMarkAsPaidIdempotent:
    """Pre-fix: two concurrent pay calls could both pass is_paid check and
    double-credit the register. We verify that a second pay call refuses."""

    def test_second_pay_attempt_rejected(
        self, order_factory, cashier_user, regular_user,
    ):
        order = order_factory(user=regular_user, cashier=cashier_user)
        result1, status1 = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status1 == 200

        result2, status2 = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status2 >= 400, 'second pay must be rejected'
