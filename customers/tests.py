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

    def test_cashier_can_modify_other_cashiers_order(
        self, order_factory, cashier_user, other_cashier_user, regular_user,
    ):
        # Shared monoblock: any cashier on the till acts on any order, even
        # one another cashier opened (mark-ready / pay / status / items).
        order = order_factory(user=regular_user, cashier=other_cashier_user)
        result = _check_cashier_ownership(
            order, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert result is None

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


class TestCancelPaidOrderReversesCash:
    """Pre-fix: cancelling a paid order flipped status to CANCELED but never
    reversed the inkassa entry, so the cash register over-reported balance.
    Now: cash payments reverse on cancel; card/Payme don't (settle externally).
    """

    def test_cancel_paid_cash_order_decrements_register(
        self, order_factory, cashier_user, regular_user,
    ):
        from decimal import Decimal
        from base.models import CashRegister
        from base.services.inkassa_service import InkassaService

        CashRegister.objects.create(current_balance=Decimal('0'))
        order = order_factory(user=regular_user, cashier=cashier_user)

        CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
            payment_method='CASH',
        )
        register = CashRegister.objects.first()
        assert register.current_balance == Decimal('10.00')

        CustomerOrderService.update_order_status(
            order.id, 'CANCELED', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        register.refresh_from_db()
        assert register.current_balance == Decimal('0.00'), \
            'paid cash order cancel must reverse the register entry'

    def test_cancel_paid_card_order_does_not_touch_register(
        self, order_factory, cashier_user, regular_user,
    ):
        from decimal import Decimal
        from base.models import CashRegister

        CashRegister.objects.create(current_balance=Decimal('0'))
        order = order_factory(user=regular_user, cashier=cashier_user)

        CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
            payment_method='UZCARD',
        )
        register = CashRegister.objects.first()
        # Card payment doesn't touch the cash drawer.
        assert register.current_balance == Decimal('0.00')

        CustomerOrderService.update_order_status(
            order.id, 'CANCELED', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        register.refresh_from_db()
        assert register.current_balance == Decimal('0.00')


class TestReverseDeductionIdempotent:
    """Pre-fix: reverse_deduction always issued RETURN_FROM_CUSTOMER for every
    SALE_OUT it found, with no check for existing reversals. Calling it twice
    (idempotency-key miss + manual retry, sync replay) phantom-credited stock."""

    def test_double_reverse_is_no_op_second_time(self, db, admin_user, order_factory, regular_user):
        from decimal import Decimal
        from stock.models import (
            StockUnit, StockLocation, StockItem, StockSettings,
        )
        from stock.repositories import StockLevelRepository
        from stock.services.level_service import StockLevelService
        from stock.services.order_service import OrderStockService

        settings = StockSettings.load()
        settings.stock_enabled = True
        settings.save()

        order = order_factory(user=regular_user)
        unit = StockUnit.objects.create(name='each', short_name='ea', unit_type='COUNT')
        loc = StockLocation.objects.create(name='Bar', type='STORAGE')
        item = StockItem.objects.create(
            name='Bottle', base_unit=unit, item_type='RAW',
            cost_price=Decimal('5'), avg_cost_price=Decimal('5'),
        )
        level = StockLevelRepository.get_or_create_level(item.id, loc.id)
        level.quantity = Decimal('100')
        level.save()

        # Simulate the SALE_OUT that order processing would have created.
        StockLevelService.adjust(
            stock_item_id=item.id, location_id=loc.id, quantity=Decimal('5'),
            movement_type='SALE_OUT', user_id=admin_user.id, order_id=order.id,
        )
        level.refresh_from_db()
        assert level.quantity == Decimal('95')

        # First reversal: stock returns to 100.
        OrderStockService.reverse_deduction(order_id=order.id, user_id=admin_user.id)
        level.refresh_from_db()
        assert level.quantity == Decimal('100')

        # Second reversal: must be a no-op, not a phantom +5.
        OrderStockService.reverse_deduction(order_id=order.id, user_id=admin_user.id)
        level.refresh_from_db()
        assert level.quantity == Decimal('100'), 'double reverse must be idempotent'


class TestCancelledSpellingContract:
    """Issue #16 / BE-5: the POS frontend keys filters and badges on the
    spelling `CANCELLED` (double L). The DB stores `CANCELED` (single L); the
    customers API must translate at the boundary in both directions."""

    def test_serializer_emits_double_l(self, order_factory, regular_user):
        order = order_factory(user=regular_user, status='CANCELED')
        result, status = CustomerOrderService.get_order_by_id(
            order.id, user_id=regular_user.id, user_role='ADMIN',
        )
        assert status == 200
        assert result['data']['order']['status'] == 'CANCELLED'

    def test_list_filter_accepts_double_l(self, order_factory, regular_user):
        cancelled = order_factory(user=regular_user, status='CANCELED')
        order_factory(user=regular_user, status='PREPARING')
        result, status = CustomerOrderService.get_all_orders(statuses='CANCELLED')
        assert status == 200
        ids = [o['id'] for o in result['data']['orders']]
        assert cancelled.id in ids
        assert all(o['status'] == 'CANCELLED' for o in result['data']['orders'])

    def test_list_filter_still_accepts_single_l(self, order_factory, regular_user):
        cancelled = order_factory(user=regular_user, status='CANCELED')
        result, _ = CustomerOrderService.get_all_orders(statuses='CANCELED')
        assert cancelled.id in [o['id'] for o in result['data']['orders']]


class TestOrderLifecycleContract:
    """BE-1 / BE-2: idempotent re-cancel and re-ready, 422 on invalid status,
    and the full order object returned on a status mutation."""

    def test_recancel_is_idempotent_200(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user, status='CANCELED')
        result, status = CustomerOrderService.update_order_status(
            order.id, 'CANCELLED', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 200
        assert result['success'] is True
        assert result['data']['order']['status'] == 'CANCELLED'

    def test_cancelled_order_cannot_transition(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user, status='CANCELED')
        result, status = CustomerOrderService.update_order_status(
            order.id, 'PREPARING', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 422
        assert result['success'] is False

    def test_invalid_status_is_422(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user, status='PREPARING')
        result, status = CustomerOrderService.update_order_status(
            order.id, 'BOGUS', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 422

    def test_status_change_returns_full_order(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user, status='PREPARING')
        result, status = CustomerOrderService.update_order_status(
            order.id, 'READY', cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 200
        body = result['data']['order']
        assert body['id'] == order.id
        assert body['status'] == 'READY'
        assert 'items' in body and 'total_amount' in body

    def test_mark_ready_is_idempotent(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user, status='READY')
        from django.utils import timezone
        order.ready_at = timezone.now()
        order.save(update_fields=['ready_at'])
        result, status = CustomerOrderService.mark_order_ready(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
        assert status == 200
        assert result['success'] is True
        assert result['data']['status'] == 'READY'


class TestSplitPayment:
    """Multi-line payments + pay-time percent discount (money math)."""

    def test_split_exact_only_cash_hits_drawer(self, order_factory, cashier_user, regular_user):
        from decimal import Decimal
        from base.models import CashRegister, OrderPayment
        CashRegister.objects.create(current_balance=Decimal('0'))
        order = order_factory(user=regular_user, cashier=cashier_user)  # total 10.00
        result, status = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id, user_id=cashier_user.id, user_role='CASHIER',
            payments=[{'method': 'HUMO', 'amount': 6}, {'method': 'CASH', 'amount': 4}],
        )
        assert status == 200, result
        order.refresh_from_db()
        assert order.is_paid and order.payment_method == 'MIXED'
        assert OrderPayment.objects.filter(order=order).count() == 2
        assert CashRegister.objects.first().current_balance == Decimal('4.00')

    def test_discount_with_cash_change(self, order_factory, cashier_user, regular_user):
        from decimal import Decimal
        from base.models import CashRegister
        CashRegister.objects.create(current_balance=Decimal('0'))
        order = order_factory(user=regular_user, cashier=cashier_user)  # total 10.00
        # 10% off -> effective 9; pay 5 HUMO + 10 CASH (6 of the cash is change)
        result, status = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id, user_id=cashier_user.id, user_role='CASHIER',
            discount_percent=10,
            payments=[{'method': 'HUMO', 'amount': 5}, {'method': 'CASH', 'amount': 10}],
        )
        assert status == 200, result
        order.refresh_from_db()
        assert order.total_amount == Decimal('9.00')
        assert order.discount_percent == Decimal('10.00')
        # cash share of the bill = effective(9) - noncash(5) = 4 (net of change)
        assert CashRegister.objects.first().current_balance == Decimal('4.00')

    def test_shortfall_rejected(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user)
        result, status = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id, user_id=cashier_user.id, user_role='CASHIER',
            payments=[{'method': 'CASH', 'amount': 7}],
        )
        assert status == 422
        order.refresh_from_db()
        assert not order.is_paid

    def test_noncash_overpay_rejected(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=cashier_user)
        result, status = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id, user_id=cashier_user.id, user_role='CASHIER',
            payments=[{'method': 'HUMO', 'amount': 12}],
        )
        assert status == 422
        order.refresh_from_db()
        assert not order.is_paid


class TestCashierShiftSelfService:
    """Shifts are manual now: the cashier opens/closes their own shift via the
    shift API, login doesn't auto-open one, and logout leaves an open shift open."""

    def test_start_current_end_lifecycle(self, cashier_user):
        from admins.services.shift_service import ShiftService

        res, st = ShiftService.start_shift(cashier_user.id)
        assert st == 201
        assert res['data']['status'] == 'ACTIVE'

        res, st = ShiftService.current_for_user(cashier_user.id)
        assert st == 200
        assert res['data'] is not None
        assert res['data']['status'] == 'ACTIVE'

        res, st = ShiftService.end_active_for_user(cashier_user.id, notes='closing')
        assert st == 200
        # Ending sets ENDED (awaiting manager reconciliation), not COMPLETED.
        assert res['data']['status'] == 'ENDED'

        # No open shift remains.
        res, st = ShiftService.current_for_user(cashier_user.id)
        assert res['data'] is None

    def test_double_start_conflicts(self, cashier_user):
        from admins.services.shift_service import ShiftService

        _, st = ShiftService.start_shift(cashier_user.id)
        assert st == 201
        _, st = ShiftService.start_shift(cashier_user.id)
        assert st >= 400  # already has an active shift

    def test_end_without_active_is_404(self, cashier_user):
        from admins.services.shift_service import ShiftService

        _, st = ShiftService.end_active_for_user(cashier_user.id)
        assert st == 404

    def test_login_does_not_autostart_shift(self, cashier_user):
        """Shifts are manual: login must NOT open a shift. The cashier opens one
        explicitly via POST /shifts/start (ShiftService.start_shift)."""
        from customers.services.auth_service import AuthService
        from base.repositories.shift import ShiftRepository
        from admins.services.shift_service import ShiftService
        from base.models import Shift

        res, st = AuthService.login(
            'cashier1@test.local', 'cashierpass', '127.0.0.1', 'pytest')
        assert st == 200
        # Login opened no shift as a side effect.
        assert ShiftRepository.get_active_for_user(cashier_user.id) is None
        assert Shift.objects.filter(user=cashier_user, status='ACTIVE').count() == 0

        # Only the explicit manual start opens one.
        _, st = ShiftService.start_shift(cashier_user.id)
        assert st == 201
        active = ShiftRepository.get_active_for_user(cashier_user.id)
        assert active is not None and active.status == 'ACTIVE'

    def test_logout_leaves_shift_open(self, cashier_user):
        from customers.services.auth_service import AuthService
        from admins.services.shift_service import ShiftService
        from base.repositories.shift import ShiftRepository

        res, st = AuthService.login(
            'cashier1@test.local', 'cashierpass', '127.0.0.1', 'pytest')
        token = res['data']['token']
        ShiftService.start_shift(cashier_user.id)

        AuthService.logout(token)

        # Shift survives logout — resume on next login.
        active = ShiftRepository.get_active_for_user(cashier_user.id)
        assert active is not None
        assert active.status == 'ACTIVE'


class TestInstantProducts:
    """is_instant products (drinks etc.) are born ready and never hit the
    kitchen / chef display."""

    def _instant_product(self, category, name='Cola'):
        from base.models import Product
        return Product.objects.create(
            name=name, price='5.00', category=category, is_instant=True,
        )

    def test_all_instant_order_is_ready_immediately(self, cashier_user, category):
        product = self._instant_product(category)
        res, st = CustomerOrderService.create_order(
            user_id=cashier_user.id,
            items=[{'product_id': product.id, 'quantity': 2}],
            cashier_id=cashier_user.id,
        )
        assert st == 201
        from base.models import Order, OrderItem
        order = Order.objects.get(id=res['data']['order_id'])
        assert order.status == 'READY'
        assert order.ready_at is not None
        assert OrderItem.objects.filter(order=order, ready_at__isnull=True).count() == 0

    def test_instant_items_excluded_from_chef_display(self, cashier_user, category, product):
        # Mixed order: one cooked item (fixture product, not instant) + one drink.
        instant = self._instant_product(category, name='Juice')
        res, st = CustomerOrderService.create_order(
            user_id=cashier_user.id,
            items=[
                {'product_id': product.id, 'quantity': 1},
                {'product_id': instant.id, 'quantity': 1},
            ],
            cashier_id=cashier_user.id,
        )
        assert st == 201
        # Order still needs the kitchen for the cooked item.
        from base.models import Order
        order = Order.objects.get(id=res['data']['order_id'])
        assert order.status == 'PREPARING'

        disp, _ = CustomerOrderService.get_chef_display_orders()
        shown = [o for o in disp['data']['orders'] if o['id'] == order.id]
        assert len(shown) == 1
        names = [it['product_name'] for it in shown[0]['items']]
        assert 'Juice' not in names  # instant drink hidden from the kitchen
        assert shown[0]['items_total'] == 1  # only the cooked item counts


class TestPaymentAttributesCashier:
    """A waiter/customer-created order (cashier_id NULL) must be credited to
    the cashier who collects payment, so it shows in that cashier's shift."""

    def test_pay_sets_cashier_when_unattributed(self, order_factory, cashier_user, regular_user):
        order = order_factory(user=regular_user, cashier=None)
        assert order.cashier_id is None
        res, st = CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER', payment_method='CASH')
        assert st == 200
        order.refresh_from_db()
        assert order.cashier_id == cashier_user.id

    def test_pay_keeps_existing_cashier(self, order_factory, cashier_user, other_cashier_user, regular_user):
        # If the order already has a cashier, paying doesn't steal attribution.
        order = order_factory(user=regular_user, cashier=other_cashier_user)
        CustomerOrderService.mark_as_paid(
            order.id, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER', payment_method='CASH')
        order.refresh_from_db()
        assert order.cashier_id == other_cashier_user.id
