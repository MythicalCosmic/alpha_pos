from django.urls import path

from licensing import views


urlpatterns = [
    path('status', views.status_view, name='licensing-status'),
    path('setup', views.setup_view, name='licensing-setup'),
]
