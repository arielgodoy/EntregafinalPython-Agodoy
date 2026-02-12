from django.contrib import admin

from .models import RegistroOperacional, AlertaAck

admin.site.register(RegistroOperacional)
admin.site.register(AlertaAck)
