from django.db import models
from django.db import models
from django.contrib.auth.models import User
# settings/models.py

from django.db import models
from django.contrib.auth.models import User

class UserPreferences(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Campos para las preferencias de tema
    data_layout = models.CharField(max_length=50, blank=True, null=True)
    data_bs_theme = models.CharField(max_length=50, blank=True, null=True)
    data_sidebar_visibility = models.CharField(max_length=50, blank=True, null=True)
    data_layout_width = models.CharField(max_length=50, blank=True, null=True)
    data_layout_position = models.CharField(max_length=50, blank=True, null=True)
    data_topbar = models.CharField(max_length=50, blank=True, null=True)
    data_sidebar_size = models.CharField(max_length=50, blank=True, null=True)
    data_layout_style = models.CharField(max_length=50, blank=True, null=True)
    data_sidebar = models.CharField(max_length=50, blank=True, null=True)
    data_sidebar_image = models.CharField(max_length=50, blank=True, null=True)
    data_preloader = models.CharField(max_length=50, blank=True, null=True)

    # Puedes agregar otros campos de preferencias aquí si es necesario

    def __str__(self):
        return f"Preferences for {self.user.username}"



