from django import forms

from settings.models import SettingsMySQLConnection

from .models import EvaluacionConnectionRole
from .services.connection_roles import (
    get_mysql_connection_catalog,
    get_system_database_catalog,
)


class EvaluacionConnectionRoleForm(forms.ModelForm):
    django_alias = forms.ChoiceField(
        choices=(),
        required=False,
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "data-role-django-alias": "true",
            }
        ),
    )

    class Meta:
        model = EvaluacionConnectionRole
        fields = (
            "source_type",
            "django_alias",
            "mysql_connection",
            "database_name",
        )
        widgets = {
            "source_type": forms.Select(
                attrs={
                    "class": "form-select",
                    "data-role-source-type": "true",
                }
            ),
            "mysql_connection": forms.Select(
                attrs={
                    "class": "form-select",
                    "data-role-mysql-connection": "true",
                }
            ),
            "database_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "off",
                    "data-role-database-name": "true",
                }
            ),
        }

    def __init__(self, *args, role: str, **kwargs):
        self.role = role
        super().__init__(*args, **kwargs)
        self.instance.role = role
        if role in EvaluacionConnectionRole.LEGACY_MYSQL_ROLES:
            self.instance.source_type = EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG
            self.instance.django_alias = None
            source_type_field = self.fields["source_type"]
            if isinstance(source_type_field, forms.ChoiceField):
                source_type_field.choices = (
                    (EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG, "Conexión MySQL"),
                )
                source_type_field.widget = forms.HiddenInput()
            self.fields["django_alias"].widget = forms.HiddenInput()
            self.show_source_selector = False
        else:
            self.show_source_selector = True
            source_type_field = self.fields["source_type"]
            source_type_field.label = "Tipo de conexión"
            source_type_field.required = True
            self.fields["django_alias"].label = "Conexión del sistema"
            django_alias_choices = [
                ("", "Seleccione una conexión del sistema"),
                *[
                    (
                        item["alias"],
                        f"{item['alias']} ({item['vendor']} / "
                        f"{item['classification']})",
                    )
                    for item in get_system_database_catalog()
                ],
            ]
            django_alias_field = self.fields["django_alias"]
            if isinstance(django_alias_field, forms.ChoiceField):
                django_alias_field.choices = django_alias_choices
        self.fields["mysql_connection"].label = "Conexión MySQL"
        self.fields["database_name"].label = "Base de datos"
        self.show_database_name = (
            role in EvaluacionConnectionRole.DATABASE_CONFIGURABLE_ROLES
        )
        if not self.show_database_name:
            self.fields.pop("database_name")
        else:
            self.fields["database_name"].required = False
        self.fields["mysql_connection"].required = False
        mysql_connection_field = self.fields["mysql_connection"]
        if isinstance(mysql_connection_field, forms.ModelChoiceField):
            mysql_connection_field.queryset = get_mysql_connection_catalog()
            mysql_connection_field.label_from_instance = self._connection_label

    @staticmethod
    def _connection_label(obj: SettingsMySQLConnection) -> str:
        empresa = obj.empresa.codigo
        descripcion = obj.empresa.descripcion
        if descripcion:
            empresa = f"{empresa} - {descripcion}"
        state = "" if obj.is_active else " (inactiva)"
        return f"{empresa} / {obj.nombre_logico}{state}"

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get(
            "source_type",
            EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
        )
        django_alias = (cleaned.get("django_alias") or "").strip()
        mysql_connection = cleaned.get("mysql_connection")

        if source_type == EvaluacionConnectionRole.SOURCE_DJANGO:
            if self.role in EvaluacionConnectionRole.LEGACY_MYSQL_ROLES:
                self.add_error(
                    None,
                    "Los roles Legacy requieren una conexión MySQL.",
                )
            if not django_alias:
                self.add_error(
                    "django_alias",
                    "Debe seleccionar un alias Django clasificado como SYSTEM.",
                )
            elif django_alias not in {
                item["alias"] for item in get_system_database_catalog()
            }:
                self.add_error(
                    "django_alias",
                    "El alias debe existir y estar clasificado como SYSTEM.",
                )
            if mysql_connection is not None:
                self.add_error(
                    "mysql_connection",
                    "No puede combinar ambas fuentes de conexión.",
                )
            cleaned["django_alias"] = django_alias or None
            cleaned["mysql_connection"] = None
            cleaned["database_name"] = None
            self.instance.database_name = None
        elif source_type == EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG:
            if mysql_connection is None:
                self.add_error(
                    "mysql_connection",
                    "Debe seleccionar una conexión MySQL activa.",
                )
            else:
                if not mysql_connection.is_active:
                    self.add_error(
                        "mysql_connection",
                        "La conexión MySQL seleccionada está inactiva.",
                    )
                engine = SettingsMySQLConnection.normalize_engine(
                    mysql_connection.engine
                )
                if engine not in {
                    SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
                    SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
                }:
                    self.add_error(
                        "mysql_connection",
                        "La conexión seleccionada no utiliza un motor SQL compatible.",
                    )
            if django_alias:
                self.add_error(
                    "django_alias",
                    "No puede combinar ambas fuentes de conexión.",
                )
            cleaned["django_alias"] = None
            if self.role in EvaluacionConnectionRole.DATABASE_CONFIGURABLE_ROLES:
                database_name = (cleaned.get("database_name") or "").strip()
                if not database_name:
                    self.add_error(
                        "database_name",
                        "Debe indicar el nombre de la base de datos.",
                    )
                elif not EvaluacionConnectionRole.DATABASE_NAME_PATTERN.fullmatch(
                    database_name
                ):
                    self.add_error(
                        "database_name",
                        "El nombre de base de datos no es válido.",
                    )
                else:
                    cleaned["database_name"] = database_name
                    self.instance.database_name = database_name
            else:
                cleaned["database_name"] = None
                self.instance.database_name = None
        else:
            self.add_error("source_type", "Tipo de conexión inválido.")

        return cleaned
