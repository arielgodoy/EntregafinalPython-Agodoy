from django.db import models
from django.contrib.auth.models import User

class UserPreferences(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Valores por defecto según layout.js / HTML base
    data_layout = models.CharField(max_length=50, blank=True, null=True, default="vertical")
    data_bs_theme = models.CharField(max_length=50, blank=True, null=True, default="light")
    data_sidebar_visibility = models.CharField(max_length=50, blank=True, null=True, default="show")
    data_layout_width = models.CharField(max_length=50, blank=True, null=True, default="fluid")
    data_layout_position = models.CharField(max_length=50, blank=True, null=True, default="fixed")
    data_topbar = models.CharField(max_length=50, blank=True, null=True, default="light")
    data_sidebar_size = models.CharField(max_length=50, blank=True, null=True, default="lg")
    data_layout_style = models.CharField(max_length=50, blank=True, null=True, default="default")
    data_sidebar = models.CharField(max_length=50, blank=True, null=True, default="dark")
    data_sidebar_image = models.CharField(max_length=50, blank=True, null=True, default="none")
    data_preloader = models.CharField(max_length=50, blank=True, null=True, default="disable")

    def __str__(self):
        return f"Preferences for {self.user.username}"
