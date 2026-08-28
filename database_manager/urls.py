from django.urls import path

from . import views

app_name = 'database_manager'

urlpatterns = [
    path('', views.DatabaseManagerDashboardView.as_view(), name='dashboard'),
    path('compare/', views.DatabaseCompareView.as_view(), name='compare'),
]
