"""Regression tests for stock math/correctness bugs."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def base_unit(db):
    from stock.models import StockUnit
    return StockUnit.objects.create(name='kilogram', short_name='kg', unit_type='WEIGHT')


@pytest.fixture
def location(db):
    from stock.models import StockLocation
    return StockLocation.objects.create(name='Main Storage', type='STORAGE')


@pytest.fixture
def stock_item(db, base_unit):
    from stock.models import StockItem
    return StockItem.objects.create(
        name='Flour', base_unit=base_unit, item_type='RAW',
        cost_price=Decimal('10'), avg_cost_price=Decimal('10'),
        last_cost_price=Decimal('10'),
    )


class TestWeightedAverageCost:
    """Pre-fix: update_cost divided new_cost by total_qty+1 regardless of
    received quantity. Receiving 100kg @ 12 vs 100kg @ 10 prior should
    yield avg = 11, not (1000 + 12) / 101 = 10.02."""

    def test_moving_average_correct_for_equal_qty_receipt(
        self, stock_item, location,
    ):
        from stock.repositories import StockLevelRepository
        from stock.services.item_service import StockItemService

        # Seed: 100kg already on hand at avg cost 10
        level = StockLevelRepository.get_or_create_level(
            stock_item.id, location.id,
        )
        level.quantity = Decimal('200')  # post-receipt qty (caller adjusts first)
        level.save()

        result, status = StockItemService.update_cost(
            stock_item.id, new_cost=Decimal('12'),
            update_type='AVG', received_qty=Decimal('100'),
        )
        assert status == 200
        stock_item.refresh_from_db()
        # (100 * 10 + 100 * 12) / 200 = 11
        assert stock_item.avg_cost_price == Decimal('11.0000')

    def test_first_receipt_sets_cost(self, stock_item, location):
        from stock.repositories import StockLevelRepository
        from stock.services.item_service import StockItemService

        level = StockLevelRepository.get_or_create_level(
            stock_item.id, location.id,
        )
        level.quantity = Decimal('50')
        level.save()

        result, status = StockItemService.update_cost(
            stock_item.id, new_cost=Decimal('15'),
            update_type='AVG', received_qty=Decimal('50'),
        )
        assert status == 200
        stock_item.refresh_from_db()
        assert stock_item.avg_cost_price == Decimal('15.0000')


class TestStockCountVarianceDirection:
    """Pre-fix: COUNT_ADJUSTMENT was abs()'d and sign was inferred from a
    magic outgoing list. Negative variance (shrinkage) became a gain."""

    def test_negative_variance_decreases_stock(self, stock_item, location):
        from stock.repositories import StockLevelRepository
        from stock.services.level_service import StockLevelService

        level = StockLevelRepository.get_or_create_level(
            stock_item.id, location.id,
        )
        level.quantity = Decimal('100')
        level.save()

        # COUNT_ADJUSTMENT with negative quantity = shrinkage
        result, status = StockLevelService.adjust(
            stock_item_id=stock_item.id,
            location_id=location.id,
            quantity=Decimal('-5'),
            movement_type='COUNT_ADJUSTMENT',
            user_id=None,
        )
        assert status == 200
        level.refresh_from_db()
        assert level.quantity == Decimal('95'), 'shrinkage must decrease stock'

    def test_positive_variance_increases_stock(self, stock_item, location):
        from stock.repositories import StockLevelRepository
        from stock.services.level_service import StockLevelService

        level = StockLevelRepository.get_or_create_level(
            stock_item.id, location.id,
        )
        level.quantity = Decimal('100')
        level.save()

        result, status = StockLevelService.adjust(
            stock_item_id=stock_item.id,
            location_id=location.id,
            quantity=Decimal('3'),
            movement_type='COUNT_ADJUSTMENT',
            user_id=None,
        )
        assert status == 200
        level.refresh_from_db()
        assert level.quantity == Decimal('103')


class TestRecipeOverDeduction:
    """Pre-fix: recipe-linked sales deducted ingredients for the FULL recipe
    yield, not divided by recipe.output_quantity. Selling 1 cookie deducted
    ingredients for all 10 cookies in the recipe."""

    def test_recipe_link_divides_by_output_quantity(
        self, stock_item, base_unit, db,
    ):
        from base.models import Category, Product
        from stock.models import (
            Recipe, RecipeIngredient, ProductStockLink, StockItem,
        )
        from stock.services.product_link_service import ProductStockLinkService

        # Output item (the cookie) and ingredient item (flour, already created)
        output_item = StockItem.objects.create(
            name='Cookie', base_unit=base_unit, item_type='FINISHED',
        )

        recipe = Recipe.objects.create(
            name='Cookie Recipe', code='COOKIE-1',
            output_item=output_item, output_quantity=Decimal('10'),
            output_unit=base_unit,
        )
        # Recipe needs 1kg flour to make 10 cookies
        RecipeIngredient.objects.create(
            recipe=recipe, stock_item=stock_item, quantity=Decimal('1'),
            unit=base_unit,
        )

        category = Category.objects.create(name='Bakery')
        product = Product.objects.create(
            name='Cookie', price='2.00', category=category,
        )
        ProductStockLink.objects.create(
            product=product, link_type='RECIPE', recipe=recipe,
            quantity_per_sale=Decimal('1'),
        )

        # Selling 1 cookie should deduct 1/10 kg flour, not 1kg
        deductions = ProductStockLinkService.get_deduction_items(
            product.id, quantity=1,
        )
        assert len(deductions) == 1
        assert deductions[0]['stock_item_id'] == stock_item.id
        assert deductions[0]['quantity'] == Decimal('0.1'), (
            f"expected 0.1 (1kg / 10 cookies * 1 sold), got {deductions[0]['quantity']}"
        )
