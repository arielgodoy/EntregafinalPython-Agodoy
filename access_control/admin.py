from django.contrib import admin

from .models import Empresa, Vista, Permiso, PerfilAcceso, PerfilAccesoDetalle, UsuarioPerfilEmpresa

admin.site.register(Empresa)
admin.site.register(Vista)
admin.site.register(Permiso)
admin.site.register(PerfilAcceso)
admin.site.register(PerfilAccesoDetalle)
admin.site.register(UsuarioPerfilEmpresa)