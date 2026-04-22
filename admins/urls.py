from django.urls import path
from admins.views import auth_views, category_views, product_views, order_views
from admins.views import place_views, app_settings_views

urlpatterns = [
    path('auth-login', auth_views.login),
    path('auth-logout', auth_views.logout),
    path('auth-logout-all', auth_views.logout_all),
    path('auth-me', auth_views.me),
    path('auth-change-password', auth_views.change_password),
    path('auth-sessions', auth_views.sessions),

    path('categories', category_views.categories),
    path('categories/active', category_views.active_categories),
    path('categories/deleted', category_views.deleted_categories),
    path('categories/stats', category_views.category_stats),
    path('categories/reorder', category_views.reorder_categories),
    path('categories/bulk-delete', category_views.bulk_delete_categories),
    path('categories/bulk-restore', category_views.bulk_restore_categories),
    path('categories/slug/<slug:slug>', category_views.category_by_slug),
    path('categories/<int:category_id>', category_views.category_detail),
    path('categories/<int:category_id>/status', category_views.update_category_status),
    path('categories/<int:category_id>/toggle', category_views.toggle_category_status),
    path('categories/<int:category_id>/restore', category_views.restore_category),

    path('products', product_views.products),
    path('products/stats', product_views.product_stats),
    path('products/deleted', product_views.deleted_products),
    path('products/bulk-delete', product_views.bulk_delete_products),
    path('products/bulk-restore', product_views.bulk_restore_products),
    path('products/category/<int:category_id>', product_views.products_by_category),
    path('products/<int:product_id>', product_views.product_detail),
    path('products/<int:product_id>/restore', product_views.restore_product),

    path('orders', order_views.orders),
    path('orders/stats', order_views.order_stats),
    path('orders/stats/daily', order_views.daily_stats),
    path('orders/stats/monthly', order_views.monthly_stats),
    path('orders/stats/yearly', order_views.yearly_stats),
    path('orders/stats/cashiers', order_views.cashier_stats),
    path('orders/stats/statuses', order_views.status_stats),
    path('orders/stats/order-types', order_views.order_type_stats),
    path('orders/stats/top-products', order_views.top_products),
    path('orders/stats/least-sold', order_views.least_sold_products),

    path('orders/stats/categories', order_views.category_stats),
    path('orders/stats/hourly', order_views.hourly_stats),

    path('orders/stats/dashboard', order_views.dashboard_stats),

    path('orders/<int:order_id>', order_views.order_detail),
    path('orders/<int:order_id>/add-item', order_views.add_item),
    path('orders/<int:order_id>/status', order_views.update_status),
    path('orders/<int:order_id>/pay', order_views.pay_order),
    path('orders/<int:order_id>/unpay', order_views.unpay_order),
    path('orders/<int:order_id>/ready', order_views.mark_ready),
    path('orders/<int:order_id>/cancel', order_views.cancel_order),
    path('orders/<int:order_id>/restore', order_views.restore_order),
    path('orders/<int:order_id>/items/<int:item_id>', order_views.update_item),
    path('orders/<int:order_id>/items/<int:item_id>/remove', order_views.remove_item),
    path('orders/<int:order_id>/items/<int:item_id>/ready', order_views.mark_item_ready),
    path('orders/<int:order_id>/items/<int:item_id>/unready', order_views.unmark_item_ready),

    path('places', place_views.places),
    path('places/<int:place_id>', place_views.place_detail),
    path('tables', place_views.tables),
    path('tables/<int:table_id>', place_views.table_detail),
    path('tables/<int:table_id>/status', place_views.table_status),
    path('tables/place/<int:place_id>', place_views.tables_by_place),

    path('app-settings', app_settings_views.app_settings),
]
