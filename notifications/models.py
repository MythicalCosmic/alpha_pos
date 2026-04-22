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
    is_enabled = models.BooleanField(default=True)
    language = models.CharField(max_length=5, default='uz')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['notification_type']

    def __str__(self):
        return f"{self.name} ({self.notification_type})"


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
