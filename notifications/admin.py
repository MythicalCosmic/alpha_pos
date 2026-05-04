from django.contrib import admin
from .models import NotificationSettings, NotificationTemplate, NotificationLog


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'brand_name', 'is_enabled', 'timeout')


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('id', 'notification_type', 'name', 'is_enabled', 'language')
    list_filter = ('is_enabled', 'language')


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'notification_type', 'recipient', 'status', 'created_at')
    list_filter = ('status', 'notification_type')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
