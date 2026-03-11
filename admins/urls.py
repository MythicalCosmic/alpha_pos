from django.urls import path
from admins.views import auth_views, category_views, product_views

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
]
