import re
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from settings.models import SettingsMySQLConnection


_DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SOURCE_DJANGO = "DJANGO"
_SOURCE_MYSQL_CONFIG = "MYSQL_CONFIG"
_DATABASE_CONFIGURABLE_ROLES = frozenset(
    {"BASE_EVALUACIONES", "AUDITORIA_EVALUACIONES"}
)
_LEGACY_MYSQL_ROLES = frozenset({"LEGACY_MYSQL", "LEGACY_AUDITORIA"})


def current_month():
    local_timezone = ZoneInfo(settings.SYSTEM_LOCAL_TIME_ZONE)
    return timezone.localdate(timezone=local_timezone).month


class EvaluacionConnectionRole(models.Model):
    SOURCE_DJANGO = _SOURCE_DJANGO
    SOURCE_MYSQL_CONFIG = _SOURCE_MYSQL_CONFIG
    SOURCE_TYPE_CHOICES: tuple[tuple[str, str], ...] = (
        (SOURCE_DJANGO, "Sistema Django"),
        (SOURCE_MYSQL_CONFIG, "Conexión MySQL"),
    )

    ROLE_BASE_EVALUACIONES = "BASE_EVALUACIONES"
    ROLE_AUDITORIA_EVALUACIONES = "AUDITORIA_EVALUACIONES"
    ROLE_LEGACY_MYSQL = "LEGACY_MYSQL"
    ROLE_LEGACY_AUDITORIA = "LEGACY_AUDITORIA"

    ROLE_CHOICES: tuple[tuple[str, str], ...] = (
        (ROLE_BASE_EVALUACIONES, "Base Evaluaciones"),
        (ROLE_AUDITORIA_EVALUACIONES, "Auditoría Evaluaciones"),
        (ROLE_LEGACY_MYSQL, "Legacy MySQL"),
        (ROLE_LEGACY_AUDITORIA, "Auditoría MySQL"),
    )
    DATABASE_CONFIGURABLE_ROLES = _DATABASE_CONFIGURABLE_ROLES
    LEGACY_MYSQL_ROLES = _LEGACY_MYSQL_ROLES
    DATABASE_NAME_PATTERN = _DATABASE_NAME_PATTERN

    role = models.CharField(max_length=40, choices=ROLE_CHOICES, unique=True)
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_MYSQL_CONFIG,
    )
    django_alias = models.CharField(max_length=100, null=True, blank=True)
    mysql_connection = models.ForeignKey(
        SettingsMySQLConnection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluaciones_connection_roles",
    )
    database_name = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            source_type=_SOURCE_DJANGO,
                            django_alias__isnull=False,
                            mysql_connection__isnull=True,
                        )
                        & ~models.Q(django_alias="")
                    )
                    | models.Q(
                        source_type=_SOURCE_MYSQL_CONFIG,
                        django_alias__isnull=True,
                        mysql_connection__isnull=False,
                    )
                ),
                name="eval_conn_role_source_chk",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        role__in=tuple(sorted(_DATABASE_CONFIGURABLE_ROLES)),
                        source_type=_SOURCE_DJANGO,
                        database_name__isnull=True,
                    )
                    | models.Q(
                        role__in=tuple(sorted(_DATABASE_CONFIGURABLE_ROLES)),
                        source_type=_SOURCE_MYSQL_CONFIG,
                        database_name__isnull=False,
                        database_name__gt="",
                    )
                    | models.Q(
                        role__in=tuple(sorted(_LEGACY_MYSQL_ROLES)),
                        source_type=_SOURCE_MYSQL_CONFIG,
                        database_name__isnull=True,
                    )
                ),
                name="eval_conn_role_db_chk",
            ),
        ]

    def clean(self):
        from .services.connection_roles import get_system_database_catalog

        errors = {}
        allowed_roles = {
            choice[0] for choice in EvaluacionConnectionRole.ROLE_CHOICES
        }
        if self.role not in allowed_roles:
            errors["role"] = "El rol de conexión de Evaluaciones no es válido."

        alias = (self.django_alias or "").strip()
        if self.source_type == self.SOURCE_DJANGO:
            if self.role in self.LEGACY_MYSQL_ROLES:
                errors["source_type"] = (
                    "Los roles Legacy requieren una conexión MySQL."
                )
            if not alias:
                errors["django_alias"] = (
                    "Debe seleccionar un alias Django clasificado como SYSTEM."
                )
            elif alias not in {
                item["alias"] for item in get_system_database_catalog()
            }:
                errors["django_alias"] = (
                    "El alias debe existir y estar clasificado como SYSTEM."
                )
            if self.mysql_connection is not None:
                errors["mysql_connection"] = (
                    "No puede combinar alias Django y conexión MySQL."
                )
            self.django_alias = alias or None
            self.database_name = None
        elif self.source_type == self.SOURCE_MYSQL_CONFIG:
            connection = self.mysql_connection
            if connection is None:
                errors["mysql_connection"] = (
                    "Debe seleccionar una conexión MySQL activa."
                )
            else:
                if not connection.is_active:
                    errors["mysql_connection"] = (
                        "La conexión MySQL seleccionada está inactiva."
                    )
                engine = SettingsMySQLConnection.normalize_engine(
                    connection.engine
                )
                if engine not in {
                    SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
                    SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
                }:
                    errors["mysql_connection"] = (
                        "La conexión seleccionada no utiliza un motor SQL compatible."
                    )
            if alias:
                errors["django_alias"] = (
                    "No puede combinar conexión MySQL y alias Django."
                )
            self.django_alias = None
            if self.role in self.DATABASE_CONFIGURABLE_ROLES:
                database_name = (self.database_name or "").strip()
                if not database_name:
                    errors["database_name"] = (
                        "Debe indicar el nombre de la base de datos."
                    )
                elif not self.DATABASE_NAME_PATTERN.fullmatch(database_name):
                    errors["database_name"] = (
                        "El nombre de base de datos no es válido."
                    )
                else:
                    self.database_name = database_name
            elif self.role in self.LEGACY_MYSQL_ROLES:
                if self.database_name:
                    errors["database_name"] = (
                        "Los roles Legacy usan el nombre de base de Settings."
                    )
                self.database_name = None
        else:
            errors["source_type"] = "Tipo de conexión inválido."

        if errors:
            raise ValidationError(errors)
        super().clean()

    def __str__(self):
        return self.get_role_display()


class Persona(models.Model):
    person_id = models.IntegerField()
    buk_employee_id = models.IntegerField(blank=True, null=True)
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    fecha_corte = models.DateField()
    rut = models.CharField(max_length=20, blank=True, null=True)
    rut_normalizado = models.CharField(max_length=20)
    full_name = models.CharField(max_length=255)
    first_name = models.CharField(max_length=100)
    surname = models.CharField(max_length=100)
    second_surname = models.CharField(max_length=100, blank=True, null=True)
    document_type = models.CharField(max_length=20)
    document_number = models.CharField(max_length=20)
    code_sheet = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    personal_email = models.EmailField(blank=True, null=True)
    address = models.CharField(max_length=255)
    street = models.CharField(max_length=100)
    street_number = models.CharField(max_length=20)
    office_number = models.CharField(max_length=20, blank=True, null=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    location_id = models.IntegerField(blank=True, null=True)
    region = models.CharField(max_length=100)
    office_phone = models.CharField(max_length=50, blank=True, null=True)
    phone = models.CharField(max_length=50)
    gender = models.CharField(max_length=1)
    birthday = models.DateField()
    active_since = models.DateField()
    active_until = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField()
    status = models.CharField(max_length=20)
    payment_method = models.CharField(max_length=50)
    payment_period = models.CharField(max_length=20)
    advance_payment = models.CharField(max_length=50)
    bank = models.CharField(max_length=50)
    account_type = models.CharField(max_length=50)
    account_number = models.CharField(max_length=50)
    private_role = models.BooleanField(default=False)
    progressive_vacations_start = models.DateField()
    nationality = models.CharField(max_length=50)
    country_code = models.CharField(max_length=10)
    civil_status = models.CharField(max_length=50)
    health_company = models.CharField(max_length=50)
    pension_regime = models.CharField(max_length=50)
    pension_fund = models.CharField(max_length=50)
    afc = models.CharField(max_length=20)
    retired = models.BooleanField(default=False)
    company_id = models.IntegerField(blank=True, null=True)
    role_id = models.IntegerField(blank=True, null=True)
    role_code = models.CharField(max_length=100, blank=True, null=True)
    role_name = models.CharField(max_length=255, blank=True, null=True)
    role_family_id = models.IntegerField(blank=True, null=True)
    role_family_name = models.CharField(max_length=255, blank=True, null=True)
    area_id = models.IntegerField(blank=True, null=True)
    cost_center = models.CharField(max_length=100, blank=True, null=True)
    recinto_asistencia_id = models.IntegerField(blank=True, null=True)
    recinto_asistencia_code = models.CharField(max_length=100, blank=True, null=True)
    recinto_primario_id = models.IntegerField(blank=True, null=True)
    recinto_primario_code = models.CharField(max_length=100, blank=True, null=True)
    ctrlit_recinto = models.CharField(max_length=100, blank=True, null=True)
    job_id = models.IntegerField(blank=True, null=True)
    job_start_date = models.DateField(blank=True, null=True)
    job_end_date = models.DateField(blank=True, null=True)
    contract_type = models.CharField(max_length=100, blank=True, null=True)
    buk_payload = models.JSONField()

    class Meta:
        verbose_name = "Persona"
        verbose_name_plural = "Personas"
        ordering = ['-anio', '-mes', 'full_name']
        constraints = [
            models.UniqueConstraint(
                fields=("anio", "mes", "rut_normalizado"),
                name="eval_person_month_rut_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(mes__gte=1, mes__lte=12),
                name="eval_person_month_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(anio__gte=1),
                name="eval_person_year_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(rut_normalizado__gt=""),
                name="eval_person_rut_nonempty_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=("anio", "mes", "company_id", "recinto_asistencia_code", "role_id"),
                name="eval_person_period_org_idx",
            ),
            models.Index(fields=("person_id",), name="eval_person_buk_person_idx"),
            models.Index(fields=("buk_employee_id",), name="eval_person_buk_emp_idx"),
            models.Index(fields=("company_id",), name="eval_person_company_idx"),
            models.Index(fields=("recinto_asistencia_code",), name="eval_person_recinto_idx"),
            models.Index(fields=("role_id",), name="eval_person_role_idx"),
        ]

    def __str__(self):
        return self.full_name
