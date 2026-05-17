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
