from django.urls import path
from . import views

app_name = 'control_operacional'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
]
