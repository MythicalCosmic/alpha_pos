from django.urls import path
from waiters.views import auth_views, order_views

urlpatterns = [
    path('auth-login', auth_views.login),
    path('auth-logout', auth_views.logout),
    path('auth-me', auth_views.me),
    path('auth-change-password', auth_views.change_password),
    path('auth-sessions', auth_views.sessions),

    path('places', order_views.places),
    path('tables', order_views.tables),
    path('tables/<int:table_id>/status', order_views.table_status),

    path('orders', order_views.my_orders),
    path('orders/create', order_views.create_order),
    path('orders/<int:order_id>', order_views.get_order),
    path('orders/<int:order_id>/add-item', order_views.add_item),
    path('orders/<int:order_id>/items/<int:item_id>', order_views.update_item),
    path('orders/<int:order_id>/items/<int:item_id>/remove', order_views.remove_item),
    path('orders/<int:order_id>/ready', order_views.mark_ready),
    path('orders/<int:order_id>/cancel', order_views.cancel_order),

    path('orders/<int:order_id>/apply-discount', order_views.apply_discount),
    path('orders/<int:order_id>/remove-discount', order_views.remove_discount),
    path('orders/<int:order_id>/check-secret-word', order_views.check_secret_word),
]
