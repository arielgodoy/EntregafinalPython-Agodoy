
from django.db import models
from django.contrib.auth.models import User


class Contratopublicidad(models.Model):
    rut_numero = models.CharField(primary_key=True, max_length=20)
    rut = models.CharField(max_length=10)  # The composite primary key (rut, numero) found, that is not supported. The first column is selected.
    numero = models.CharField(max_length=10)
    fechainicio = models.DateField()
    fechatermino = models.DateField()
    facturar = models.CharField(max_length=1)
    base = models.CharField(max_length=1)
    monto = models.FloatField()
    descontado = models.IntegerField()
    rutcontacto = models.CharField(max_length=10)
    nombrecontacto = models.CharField(max_length=50)
    glosa = models.TextField()
    def save(self, *args, **kwargs):
        self.rut_numero = f"{self.rut}_{self.numero}"  # Combina los valores
        super().save(*args, **kwargs)
    class Meta:
        managed = False
        db_table = 'contratopublicidad'
        unique_together = (('rut', 'numero'),)

from django.db import models

class LmovimientosDetalle19(models.Model):
    id = models.AutoField(primary_key=True) 
    tipo = models.CharField(max_length=2)
    numero = models.CharField(max_length=10)
    linea = models.FloatField()
    rut = models.CharField(max_length=10)
    fecha = models.DateField()
    codigo = models.CharField(max_length=13)
    descripcion = models.CharField(max_length=50)
    cantidad = models.FloatField()
    uxc = models.FloatField()
    unidades = models.FloatField()
    precio = models.FloatField()
    descuento = models.FloatField()
    total = models.FloatField()
    costoventa = models.FloatField()
    bodega = models.CharField(max_length=2)
    bodegatraspaso = models.CharField(max_length=2)
    stocktransaccion = models.FloatField()

    class Meta:
        managed = False
        db_table = 'l_movimientos_detalle_19'
        unique_together = (('tipo', 'numero', 'linea', 'rut', 'fecha', 'codigo', 'bodega'),)


class ApiToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=150)
    prefix = models.CharField(max_length=32, unique=True)
    token_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_api_tokens",
    )

    @property
    def is_expired(self):
        from django.utils import timezone

        return self.expires_at is not None and self.expires_at <= timezone.now()

