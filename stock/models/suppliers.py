"""Suppliers models for the stock app.

Auto-extracted from the original monolithic stock/models.py (smart_pos T5
refactor). Cross-model FKs are still expressed as direct class references
where the referenced model lives in this same submodule; FKs that cross
submodules are expressed as string refs like `'stock.StockUnit'` to avoid
import-order coupling.
"""
from django.db import models

from base.models import SyncMixin, SyncManager

class Supplier(SyncMixin, models.Model):

    code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True, default="")
    contact_person = models.CharField(max_length=100, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    mobile = models.CharField(max_length=50, blank=True, default="")
    address = models.TextField(blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    country = models.CharField(max_length=100, blank=True, default="")
    tax_id = models.CharField(max_length=50, blank=True, default="")

    payment_terms_days = models.PositiveIntegerField(default=30)
    credit_limit = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    current_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    currency = models.CharField(max_length=3, default="UZS")
    lead_time_days = models.PositiveIntegerField(default=1)
    minimum_order_value = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1 to 5"
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SupplierStockItem(SyncMixin, models.Model):

    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name="stock_items"
    )
    stock_item = models.ForeignKey(
        'stock.StockItem', on_delete=models.CASCADE, related_name="suppliers"
    )
    supplier_sku = models.CharField(max_length=50, blank=True, default="")
    supplier_name = models.CharField(
        max_length=200, blank=True, default="",
        help_text="What the supplier calls this item",
    )
    unit = models.ForeignKey('stock.StockUnit', on_delete=models.PROTECT, related_name="+")
    price = models.DecimalField(max_digits=15, decimal_places=4)
    currency = models.CharField(max_length=3, default="UZS")
    min_order_qty = models.DecimalField(
        max_digits=15, decimal_places=4, default=1
    )
    pack_size = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    is_preferred = models.BooleanField(default=False)
    last_price_update = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SyncManager()

    class Meta:
        unique_together = [("supplier", "stock_item")]

    def to_sync_dict(self):
        data = super().to_sync_dict()
        data['supplier_uuid'] = str(self.supplier.uuid) if self.supplier else None
        data['stock_item_uuid'] = str(self.stock_item.uuid) if self.stock_item else None
        data['unit_uuid'] = str(self.unit.uuid) if self.unit else None
        return data

    def __str__(self):
        return f"{self.supplier.name} → {self.stock_item.name}"
