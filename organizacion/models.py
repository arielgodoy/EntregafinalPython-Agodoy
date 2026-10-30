from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, models
from django.utils import timezone


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


class MembershipQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("organizacion.memberships.bulk_write_forbidden")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("organizacion.memberships.bulk_write_forbidden")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("organizacion.memberships.bulk_write_forbidden")

    def delete(self):
        raise ValidationError("organizacion.memberships.physical_delete_forbidden")


def _membership_database(instance, using):
    alias = using or instance._state.db or DEFAULT_DB_ALIAS
    if alias != DEFAULT_DB_ALIAS or instance._state.db not in (None, DEFAULT_DB_ALIAS):
        raise ValidationError("organizacion.memberships.invalid_database")
    return alias


class MembresiaDepartamental(models.Model):
    """Persistence only; coordinated, audited transitions belong to T176/T177."""

    empresa_id: int | None
    departamento_id: int | None
    usuario_id: int | None

    class Rol(models.TextChoices):
        JEFE = "JEFE", "JEFE"
        SUPERVISOR = "SUPERVISOR", "SUPERVISOR"
        STAFF = "STAFF", "STAFF"

    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "ACTIVA"
        SUSPENDIDA = "SUSPENDIDA", "SUSPENDIDA"
        BAJA = "BAJA", "BAJA"

    empresa = models.ForeignKey(
        "access_control.Empresa", on_delete=models.PROTECT, related_name="membresias_departamentales"
    )
    departamento = models.ForeignKey(
        Departamento, on_delete=models.PROTECT, related_name="membresias"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="membresias_departamentales"
    )
    rol = models.CharField(max_length=10, choices=Rol.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = MembershipQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("usuario", "empresa", "departamento"), name="org_membresia_identidad_unica"
            ),
            models.UniqueConstraint(
                fields=("departamento",), condition=models.Q(rol="JEFE", estado="ACTIVA"),
                name="org_departamento_jefe_activo",
            ),
            models.CheckConstraint(
                condition=models.Q(rol__in=("JEFE", "SUPERVISOR", "STAFF")),
                name="org_membresia_rol_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=("ACTIVA", "SUSPENDIDA", "BAJA")),
                name="org_membresia_estado_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="org_membresia_version_positiva"
            ),
        ]
        indexes = [
            models.Index(fields=("empresa", "usuario", "estado"), name="org_memb_empresa_usuario"),
            models.Index(fields=("empresa", "departamento", "estado"), name="org_memb_empresa_depto"),
        ]

    def clean(self):
        super().clean()
        department_company = Departamento.objects.using(DEFAULT_DB_ALIAS).filter(
            pk=self.departamento_id
        ).values_list("empresa_id", flat=True).first()
        if department_company is not None and department_company != self.empresa_id:
            raise ValidationError({"departamento": "organizacion.memberships.company_mismatch"})
        previous = (
            type(self).objects.using(DEFAULT_DB_ALIAS).filter(pk=self.pk).first()
            if self.pk else None
        )
        if previous is not None:
            identity = ("empresa_id", "departamento_id", "usuario_id")
            if any(getattr(self, field) != getattr(previous, field) for field in identity):
                raise ValidationError("organizacion.memberships.immutable_identity")
            changed = (self.rol, self.estado) != (previous.rol, previous.estado)
            if self.version is not None and (
                self.version < previous.version or (changed and self.version <= previous.version)
            ):
                raise ValidationError({"version": "organizacion.memberships.stale_version"})

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        using = _membership_database(self, using)
        self.full_clean()
        if update_fields is not None and {"rol", "estado"} & set(update_fields):
            update_fields = set(update_fields) | {"version", "updated_at"}
        return super().save(
            force_insert=force_insert, force_update=force_update,
            using=using, update_fields=update_fields,
        )

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("organizacion.memberships.physical_delete_forbidden")


class EventoMembresia(models.Model):
    membresia_id: int | None
    empresa_id: int | None
    usuario_afectado_id: int | None
    departamento_id: int | None
    autor_id: int | None

    membresia = models.ForeignKey(
        MembresiaDepartamental, on_delete=models.PROTECT, related_name="eventos"
    )
    empresa = models.ForeignKey("access_control.Empresa", on_delete=models.PROTECT, related_name="+")
    usuario_afectado = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    departamento = models.ForeignKey(Departamento, on_delete=models.PROTECT, related_name="+")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    fecha = models.DateTimeField(default=timezone.now, editable=False)
    operacion_id = models.UUIDField()
    secuencia = models.PositiveIntegerField(default=1)
    tipo = models.CharField(max_length=32)
    motivo = models.TextField()
    rol_antes = models.CharField(
        max_length=10, choices=MembresiaDepartamental.Rol.choices, null=True, blank=True
    )
    estado_antes = models.CharField(
        max_length=10, choices=MembresiaDepartamental.Estado.choices, null=True, blank=True
    )
    version_antes = models.PositiveBigIntegerField(null=True, blank=True)
    rol_despues = models.CharField(max_length=10, choices=MembresiaDepartamental.Rol.choices)
    estado_despues = models.CharField(max_length=10, choices=MembresiaDepartamental.Estado.choices)
    version_despues = models.PositiveBigIntegerField()
    objects = MembershipQuerySet.as_manager()

    class Meta:
        ordering = ("fecha", "pk")
        constraints = [
            models.UniqueConstraint(fields=("operacion_id", "secuencia"), name="org_evento_operacion_secuencia"),
            models.CheckConstraint(condition=models.Q(secuencia__gte=1), name="org_evento_secuencia_positiva"),
            models.CheckConstraint(condition=models.Q(version_despues__gte=1), name="org_evento_version_positiva"),
        ]
        indexes = [models.Index(fields=("empresa", "membresia", "fecha"), name="org_evento_empresa_membresia")]

    def clean(self):
        super().clean()
        if not self.motivo or not self.motivo.strip():
            raise ValidationError({"motivo": "organizacion.memberships.reason_required"})
        member = MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).filter(
            pk=self.membresia_id
        ).first()
        if member is not None and (
            self.empresa_id != member.empresa_id
            or self.departamento_id != member.departamento_id
            or self.usuario_afectado_id != member.usuario_id
        ):
            raise ValidationError("organizacion.memberships.event_reference_mismatch")
        before = (self.rol_antes, self.estado_antes, self.version_antes)
        if any(value is None for value in before) and not all(value is None for value in before):
            raise ValidationError("organizacion.memberships.incomplete_previous_state")
        if self.version_antes is not None and (
            self.rol_antes not in MembresiaDepartamental.Rol.values
            or self.estado_antes not in MembresiaDepartamental.Estado.values
        ):
            raise ValidationError("organizacion.memberships.incomplete_previous_state")
        if self.version_antes is not None and self.version_despues is not None:
            if self.version_antes < 1 or self.version_despues <= self.version_antes:
                raise ValidationError("organizacion.memberships.stale_version")

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        using = _membership_database(self, using)
        if not self._state.adding or force_update or update_fields is not None:
            raise ValidationError("organizacion.memberships.immutable_event")
        self.full_clean()
        return super().save(force_insert=True, using=using)

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("organizacion.memberships.physical_delete_forbidden")


class ControlOrganizacionEmpresa(models.Model):
    """Durable identity for the future fence; this model does not acquire locks."""

    empresa = models.OneToOneField(
        "access_control.Empresa", on_delete=models.PROTECT, related_name="control_organizacion"
    )
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(version__gte=1), name="org_control_version_positiva")
        ]

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        using = _membership_database(self, using)
        return super().save(
            force_insert=force_insert, force_update=force_update,
            using=using, update_fields=update_fields,
        )