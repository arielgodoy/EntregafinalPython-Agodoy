from django.urls import path

from . import views

urlpatterns = [
    path("menu/", views.menu_search, name="menu_search"),
]
