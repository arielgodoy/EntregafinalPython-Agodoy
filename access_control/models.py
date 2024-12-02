from django.db import models
from django.contrib.auth.models import User

class Empresa(models.Model):
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    usuarios = models.ManyToManyField(User, related_name="empresas")

    def __str__(self):
        return self.nombre


class Vista(models.Model):
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre


class Permiso(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    vista = models.ForeignKey(Vista, on_delete=models.CASCADE)
    ingresar = models.BooleanField(default=False)
    crear = models.BooleanField(default=False)
    modificar = models.BooleanField(default=False)
    eliminar = models.BooleanField(default=False)
    autorizar = models.BooleanField(default=False)
    supervisor = models.BooleanField(default=False)

    class Meta:
        unique_together = ('usuario', 'empresa', 'vista')

    def __str__(self):
        return f"{self.usuario.username} - {self.vista.nombre} - {self.empresa.nombre}"
