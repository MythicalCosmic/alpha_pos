from django.urls import path
from notifications.views import notification_views

app_name = 'notifications'

urlpatterns = [
    path('settings/', notification_views.settings_view, name='settings'),
    path('settings/test/', notification_views.settings_test, name='settings-test'),
    path('settings/status/', notification_views.settings_status, name='settings-status'),
    path('types/', notification_views.notification_types, name='type-list'),
    path('types/<str:type_slug>/', notification_views.notification_type_detail, name='type-detail'),
    path('templates/', notification_views.templates_list, name='template-list'),
    path('templates/<int:template_id>/', notification_views.template_detail, name='template-detail'),
    path('templates/<int:template_id>/preview/', notification_views.template_preview, name='template-preview'),
    path('queue/', notification_views.queue_view, name='queue'),
    path('queue/process/', notification_views.queue_process, name='queue-process'),
    path('queue/clear/', notification_views.queue_clear, name='queue-clear'),
    path('logs/', notification_views.logs_view, name='logs'),
]
