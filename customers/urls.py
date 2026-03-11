from django.urls import path
from customers.views import auth_views, category_views

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
]
