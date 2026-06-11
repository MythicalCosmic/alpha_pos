from django.urls import path
from customers.views import (auth_views, category_views, product_views,
                            order_views, staff_views, payment_views, shift_views)

urlpatterns = [
    # Pre-login cashier picker for the monoblock. Public (no session): the
    # frontend lists cashiers here, then submits email + password to
    # /auth-login, which verifies the password. Shifts are opened separately
    # via POST /shifts/start — login no longer starts one.
    path('cashiers', staff_views.list_cashiers),

    # Payment-method catalog for the cashier payment screen (staff-auth).
    path('payment-methods', payment_views.payment_methods),

    # Cashier-facing shift control (own shift; manual start/end + resume).
    path('shifts/start', shift_views.start_shift),
    path('shifts/end', shift_views.end_shift),
    path('shifts/current', shift_views.current_shift),

    path('auth-login', auth_views.login),
    path('auth-logout', auth_views.logout),
    path('auth-logout-all', auth_views.logout_all),
    path('auth-me', auth_views.me),
    path('auth-change-password', auth_views.change_password),
    path('auth-sessions', auth_views.sessions),

    path('categories', category_views.list_categories),
    path('categories/active', category_views.active_categories),
    path('categories/slug/<slug:slug>', category_views.get_category_by_slug),
    path('categories/<int:category_id>', category_views.get_category),

    path('products', product_views.list_products),
    path('products/category/<int:category_id>', product_views.products_by_category),
    path('products/<int:product_id>', product_views.get_product),

    path('orders', order_views.list_orders),
    path('orders/create', order_views.create_order),
    path('orders/client-display', order_views.client_display),
    path('orders/chef-display', order_views.chef_display),
    path('orders/<int:order_id>', order_views.get_order),
    path('orders/<int:order_id>/add-item', order_views.add_item),
    path('orders/<int:order_id>/status', order_views.update_status),
    path('orders/<int:order_id>/pay', order_views.pay_order),
    path('orders/<int:order_id>/ready', order_views.mark_ready),
    path('orders/<int:order_id>/cancel', order_views.cancel_order),
    path('orders/<int:order_id>/items/<int:item_id>', order_views.update_item),
    path('orders/<int:order_id>/items/<int:item_id>/remove', order_views.remove_item),
    path('orders/<int:order_id>/items/<int:item_id>/ready', order_views.mark_item_ready),
    path('orders/<int:order_id>/items/<int:item_id>/unready', order_views.unmark_item_ready),

    path('orders/<int:order_id>/apply-discount', order_views.apply_discount),
    path('orders/<int:order_id>/remove-discount', order_views.remove_discount),
    path('orders/<int:order_id>/check-secret-word', order_views.check_secret_word),
]
