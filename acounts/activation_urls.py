from django.urls import path
from acounts.activation_views import activate_account

app_name = "acounts_activation"

urlpatterns = [
    path('activate/<str:token>/', activate_account, name='activate'),
]
