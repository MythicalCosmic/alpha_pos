from django.db import models


class NotificationSettings(models.Model):
    bot_token = models.CharField(max_length=200, blank=True, default='')
    chat_ids = models.JSONField(default=list, blank=True)
    brand_name = models.CharField(max_length=100, default='Alpha POS')
    is_enabled = models.BooleanField(default=True)
    timeout = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'notification settings'
        verbose_name_plural = 'notification settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Notification Settings ({self.brand_name})"


class NotificationTemplate(models.Model):
    notification_type = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    template_text = models.TextField()
    # Free-text description listing which placeholders are valid for this
    # template type. Surfaced on the admin UI so editors don't have to read
    # the source to know what {variables} they can use.
    description = models.TextField(
        blank=True, default='',
        help_text='Document the available {placeholders} for this template.',
    )
    is_enabled = models.BooleanField(default=True)
    language = models.CharField(max_length=5, default='uz')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['notification_type']

    def __str__(self):
        return f"{self.name} ({self.notification_type})"


class TelegramCustomer(models.Model):
    """Customer-side Telegram account record.

    Created the first time a Telegram user opens the bot (`/start`).
    Optionally linked to a `base.User` once the customer authenticates
    inside the bot — pre-link, the row tracks the chat for greetings and
    order-status pushes only.

    Not a SyncMixin: chat-id↔user mapping is per-deployment and shouldn't
    propagate across branches.
    """

    chat_id = models.BigIntegerField(unique=True, db_index=True)
    user = models.ForeignKey(
        'base.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='telegram_customers',
    )
    first_name = models.CharField(max_length=64, blank=True, default='')
    last_name = models.CharField(max_length=64, blank=True, default='')
    username = models.CharField(max_length=64, blank=True, default='')
    language_code = models.CharField(max_length=8, blank=True, default='')
    # Saved when the user taps the request_contact button on /login.
    # Used to match TelegramCustomer ↔ existing Orders by phone_number,
    # and as the foundation for the upcoming loyalty linkage.
    phone_number = models.CharField(
        max_length=20, blank=True, default='', db_index=True,
    )
    # Set true when sendMessage returns 403 (user blocked the bot). Avoids
    # hammering Telegram with messages that will keep failing.
    is_blocked = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen_at']
        verbose_name = 'telegram customer'

    def __str__(self):
        label = self.username or self.first_name or str(self.chat_id)
        return f'TelegramCustomer<{label}>'


class LoyaltySettings(models.Model):
    """Singleton holding stamps-per-order and stamps-per-reward thresholds.

    `pk` is pinned to 1 in save() so there is exactly one row, mirroring the
    pattern used by NotificationSettings. An admin endpoint reads/writes
    this row; the loyalty service consults it on every accrual.
    """
    is_enabled = models.BooleanField(default=True)
    stamps_per_completed_order = models.PositiveIntegerField(default=1)
    stamps_per_reward = models.PositiveIntegerField(default=10)
    reward_description = models.CharField(
        max_length=120, default='Bepul ichimlik',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'loyalty settings'
        verbose_name_plural = 'loyalty settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'LoyaltySettings(per_order={self.stamps_per_completed_order}, per_reward={self.stamps_per_reward})'


class LoyaltyAccount(models.Model):
    """Per-customer stamp ledger, keyed by phone number.

    Phone is the link key (not chat_id) because the same person may have
    multiple Telegram clients (mobile + desktop) producing different chat_ids
    over time, and because orders are placed against a phone — not against a
    Telegram account. The bot looks up the account via TelegramCustomer.phone
    after /login.
    """
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    stamps_balance = models.PositiveIntegerField(default=0)
    stamps_earned_total = models.PositiveIntegerField(default=0)
    stamps_redeemed_total = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'loyalty account'

    def __str__(self):
        return f'LoyaltyAccount<{self.phone_number}: {self.stamps_balance}>'


class OrderLoyaltyCredit(models.Model):
    """Idempotency record: which orders already credited loyalty stamps.

    An order can hit the accrual hook from two paths (status→COMPLETED and
    mark_as_paid when already COMPLETED). A unique row per order_id ensures
    a second pass is a silent no-op instead of double-crediting stamps.
    """
    order_id = models.IntegerField(unique=True, db_index=True)
    phone_number = models.CharField(max_length=20, db_index=True)
    stamps_credited = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'OrderLoyaltyCredit<order={self.order_id} +{self.stamps_credited}>'


class Cart(models.Model):
    """One-active-cart-per-TelegramCustomer holding items in progress.

    The cart is the customer's draft order before checkout. We keep it
    server-side (rather than reconstructing from messages) so the customer
    can browse /menu in between adds without losing state. On /order
    checkout, the cart is converted to a real base.Order and the row stays
    for history (status=CHECKED_OUT) — never deleted, so we can recover
    if the resulting Order failed to persist.
    """
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        CHECKED_OUT = 'CHECKED_OUT', 'Checked out'
        ABANDONED = 'ABANDONED', 'Abandoned'

    customer = models.ForeignKey(
        'notifications.TelegramCustomer',
        on_delete=models.CASCADE,
        related_name='carts',
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE,
        db_index=True,
    )
    # The base.Order this cart became, if checkout succeeded.
    order = models.ForeignKey(
        'base.Order', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_carts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            # Enforce exactly one ACTIVE cart per customer at DB level so a
            # race between two simultaneous /order add calls can't create
            # two parallel carts. The status field is part of the index so
            # checked-out carts (historical) don't clash.
            models.UniqueConstraint(
                fields=['customer'], condition=models.Q(status='ACTIVE'),
                name='one_active_cart_per_customer',
            ),
        ]

    def __str__(self):
        return f'Cart<customer={self.customer_id} status={self.status}>'


class CartItem(models.Model):
    """A line on a Cart. Price is snapshotted at add time so a mid-cart
    price change on the menu doesn't surprise the customer at checkout."""
    cart = models.ForeignKey(
        Cart, on_delete=models.CASCADE, related_name='items',
    )
    product = models.ForeignKey(
        'base.Product', on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            # One row per (cart, product). /order add bumps quantity on the
            # existing row instead of creating duplicates.
            models.UniqueConstraint(
                fields=['cart', 'product'], name='unique_product_per_cart',
            ),
        ]

    def __str__(self):
        return f'CartItem<{self.product_id} x{self.quantity}>'


class NotificationLog(models.Model):
    class Status(models.TextChoices):
        SENT = 'SENT', 'Sent'
        FAILED = 'FAILED', 'Failed'
        QUEUED = 'QUEUED', 'Queued'

    notification_type = models.CharField(max_length=50)
    recipient = models.CharField(max_length=50)
    message_text = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} -> {self.recipient} ({self.status})"
