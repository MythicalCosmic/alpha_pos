"""
URL configuration for alpha_pos project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

from base.services.sync.views import get_sync_urls
from notifications.views import telegram_views, qr_order_views


def healthz(_request):
    return HttpResponse('ok', content_type='text/plain')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz', healthz),
    path('api/admins/', include('admins.urls')),
    path('api/admins/stock/', include('stock.urls')),
    path('api/admins/hr/', include('hr.urls')),
    path('api/admins/discounts/', include('discounts.urls')),
    path('api/admins/notifications/', include('notifications.urls')),
    path('api/waiters/', include('waiters.urls')),
    path('api/sync/', include(get_sync_urls())),
    # Telegram webhook lives at the root (not under /api/admins) because
    # Telegram delivers it directly with a secret-token header instead of
    # a session. Keep it short and stable so reconfiguring setWebhook is
    # rare.
    path('api/telegram/webhook/', telegram_views.webhook, name='telegram-webhook'),
    # Public QR self-order. No auth — signed token in the URL identifies the
    # table. See notifications/services/qr_order_service.py for the signing
    # scheme; rate-limited per IP via base.security.rate_limit.
    path('api/qr/menu/<str:token>/', qr_order_views.menu_view, name='qr-menu'),
    path('api/qr/order/<str:token>/', qr_order_views.order_view, name='qr-order'),
    path('', include('customers.urls')),
]
