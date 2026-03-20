from django.urls import path
from customers.views import auth_views, category_views, product_views, order_views

urlpatterns = [
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
]
