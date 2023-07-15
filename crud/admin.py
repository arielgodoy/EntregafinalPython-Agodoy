from django.contrib import admin
from .models import *
from django.contrib.auth import admin as auth_admin


# Register your models here.
#admin.site.register(User)
admin.site.register(Documento)
admin.site.register(Propiedades)
admin.site.register(Propietario)




