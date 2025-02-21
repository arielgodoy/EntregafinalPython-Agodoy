from django.contrib import admin
from .models import TipoDocumento,Propietario,Propiedad,Documento
# Register your models here.

admin.site.register(TipoDocumento)
admin.site.register(Propietario)
admin.site.register(Propiedad)
admin.site.register(Documento)



#admin.site.register(MiUsuario)