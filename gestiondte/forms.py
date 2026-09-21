from django import forms
import os
from .models import CertificadoSII, GestionDTEConnectionRole
from .utils.maestro import get_maestroempresa_by_codigo
from .services.rpetc import RPETCParameterError, validar_parametros_cesiones
from .services.connection_roles import get_active_mysql_connection_catalog, get_system_database_catalog


class CertificadoUploadForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False, label='Contraseña PFX')
    password_confirm = forms.CharField(widget=forms.PasswordInput, required=False, label='Confirmar contraseña')

    class Meta:
        model = CertificadoSII
        fields = ['empresa_codigo', 'archivo', 'password', 'password_confirm', 'activo']

    def clean_empresa_codigo(self):
        codigo = self.cleaned_data.get('empresa_codigo')
        if not codigo:
            raise forms.ValidationError('Código de empresa es requerido')
        empresa = get_maestroempresa_by_codigo(codigo)
        if not empresa:
            raise forms.ValidationError('Empresa contable no encontrada')
        # attach nombre/rut for view usage
        self.cleaned_data['_empresa_info'] = empresa
        return codigo

    def clean(self):
        cleaned = super().clean()
        pwd = cleaned.get('password')
        pwdc = cleaned.get('password_confirm')
        if pwd or pwdc:
            if pwd != pwdc:
                raise forms.ValidationError('Las contraseñas no coinciden')
        return cleaned

    def clean_archivo(self):
        f = self.cleaned_data.get('archivo')
        if not f:
            return f
        _, ext = os.path.splitext(f.name or '')
        ext = ext.lower()
        if ext not in ('.pfx', '.p12'):
            raise forms.ValidationError('Solo se permiten archivos .pfx o .p12')
        return f

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        pwd = self.cleaned_data.get('password')
        if pwd:
            instance.set_password(pwd)
        if user and not instance.pk:
            instance.created_by = user
            instance.created_by_username = user.username
        instance.updated_by = user
        instance.updated_by_username = user.username if user else None
        if commit:
            instance.save()
        return instance


class SincronizarCesionesRPETCForm(forms.Form):
    grabar_en_contabilidad = forms.BooleanField(
        required=False,
        initial=False,
        label='Grabar cesión en contabilidad',
    )
    fecha_desde = forms.DateField(
        label='Desde',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    fecha_hasta = forms.DateField(
        label='Hasta',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean(self):
        cleaned = super().clean()
        fecha_desde = cleaned.get('fecha_desde')
        fecha_hasta = cleaned.get('fecha_hasta')
        if fecha_desde and fecha_hasta:
            try:
                validar_parametros_cesiones(
                    fecha_desde.strftime('%d%m%Y'),
                    fecha_hasta.strftime('%d%m%Y'),
                    'TXT',
                )
            except RPETCParameterError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return cleaned


class GestionDTEConnectionRoleForm(forms.ModelForm):
    class Meta:
        model = GestionDTEConnectionRole
        fields = ('source_type', 'django_alias', 'mysql_connection', 'database_name')
        widgets = {
            'source_type': forms.Select(attrs={'data-role-source-type': 'true'}),
            'django_alias': forms.Select(attrs={'data-role-django-alias': 'true'}),
            'mysql_connection': forms.Select(attrs={'data-role-mysql-connection': 'true'}),
            'database_name': forms.TextInput(attrs={'data-role-database-name': 'true'}),
        }

    def __init__(self, *args, **kwargs):
        self.role = kwargs.pop('role', None)
        super().__init__(*args, **kwargs)
        self.role = self.role or self.instance.role
        self.show_database_name = self.role in GestionDTEConnectionRole.DATABASE_CONFIGURABLE_ROLES
        if not self.show_database_name:
            self.fields.pop('database_name')
        elif not self.is_bound and not self.instance.database_name:
            self.initial['database_name'] = {
                'serverbasedte': 'gestiondte',
                'serverauditoriagestiondte': 'gestiondte_auditoria',
            }[self.role]
        django_alias_choices = [
            ('', 'Seleccione una conexión del sistema'),
            *[
                (
                    item['alias'],
                    f"{item['alias']} ({item['vendor']} / {item['classification']})",
                )
                for item in get_system_database_catalog()
            ],
        ]
        self.fields['django_alias'].choices = django_alias_choices
        self.fields['django_alias'].widget.choices = django_alias_choices
        self.fields['django_alias'].required = False
        self.fields['mysql_connection'].queryset = get_active_mysql_connection_catalog()
        self.fields['mysql_connection'].required = False
        self.fields['mysql_connection'].label_from_instance = (
            lambda connection: f"{connection.empresa.codigo} - "
            f"{connection.empresa.descripcion or 'Sin descripción'} / "
            f"{connection.nombre_logico}"
        )
        self.fields['source_type'].required = False

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get('source_type')
        django_alias = (cleaned.get('django_alias') or '').strip()
        mysql_connection = cleaned.get('mysql_connection')

        if source_type == 'DJANGO':
            if not django_alias:
                self.add_error('django_alias', 'Debe seleccionar un alias Django SYSTEM.')
            if mysql_connection is not None:
                self.add_error('mysql_connection', 'No puede combinar ambas fuentes.')
            cleaned['django_alias'] = django_alias or None
            cleaned['mysql_connection'] = None
            cleaned['database_name'] = None
            self.instance.database_name = None
        elif source_type == 'MYSQL_CONFIG':
            if mysql_connection is None:
                self.add_error('mysql_connection', 'Debe seleccionar una conexión MySQL activa.')
            if django_alias:
                self.add_error('django_alias', 'No puede combinar ambas fuentes.')
            cleaned['django_alias'] = None
            if self.role not in GestionDTEConnectionRole.DATABASE_CONFIGURABLE_ROLES:
                cleaned['database_name'] = None
                self.instance.database_name = None
        else:
            self.add_error('source_type', 'Debe seleccionar el tipo de conexión.')

        return cleaned
