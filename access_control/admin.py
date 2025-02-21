from django.contrib import admin

from .models import Empresa, Vista, Permiso

admin.site.register(Empresa)
admin.site.register(Vista)
admin.site.register(Permiso)