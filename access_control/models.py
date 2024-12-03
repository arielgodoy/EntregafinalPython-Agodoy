from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator


class Empresa(models.Model):

    codigo = models.CharField(
    max_length=2,
    unique=True,
    validators=[
        RegexValidator(
            regex=r'^\d{2}$',
            message="El código debe ser un número de 2 dígitos entre 00 y 99."
        )
    ],
    verbose_name="Código"
)

    
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion or 'Sin descripción'}"


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
