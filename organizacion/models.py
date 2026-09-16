from django.db import models


class OrganizationalSource(models.TextChoices):
    ERP = "ERP", "ERP"
    LOCAL = "LOCAL", "Local"


class Local(models.Model):
    empresa = models.ForeignKey(
        "access_control.Empresa",
        on_delete=models.PROTECT,
        related_name="locales",
    )
    codigo = models.CharField(max_length=100)
    nombre = models.CharField(max_length=255)
    legacy_code = models.CharField(max_length=100, null=True, blank=True)
    activo = models.BooleanField(default=True)
    source = models.CharField(max_length=5, choices=OrganizationalSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("empresa", "codigo"),
                name="unique_local_codigo_por_empresa",
            )
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Departamento(models.Model):
    empresa = models.ForeignKey(
        "access_control.Empresa",
        on_delete=models.PROTECT,
        related_name="departamentos",
    )
    codigo = models.CharField(max_length=100)
    nombre = models.CharField(max_length=255)
    activo = models.BooleanField(default=True)
    source = models.CharField(max_length=5, choices=OrganizationalSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("empresa", "codigo"),
                name="unique_departamento_codigo_por_empresa",
            )
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"