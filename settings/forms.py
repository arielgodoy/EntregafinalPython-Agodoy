from django import forms
from .models import SettingsMySQLConnection
import re


class EngineSelect(forms.Select):
    def __init__(self, *args, option_data_keys=None, **kwargs):
        self.option_data_keys = option_data_keys or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        data_key = self.option_data_keys.get(value)
        if data_key:
            option.setdefault('attrs', {})
            option['attrs']['data-key'] = data_key
        return option


class SettingsMySQLConnectionForm(forms.ModelForm):
    ENGINE_CHOICES = (
        (SettingsMySQLConnection.ENGINE_DJANGO_MYSQL, "MySQL Django"),
        (SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL, "MySQL Legacy PyMySQL"),
        (SettingsMySQLConnection.ENGINE_API_REMOTA, "API remota"),
    )

    ENGINE_OPTION_DATA_KEYS = {
        SettingsMySQLConnection.ENGINE_DJANGO_MYSQL: "settings.mysql_connections.engine.mysql_django",
        SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL: "settings.mysql_connections.engine.legacy_pymysql",
        SettingsMySQLConnection.ENGINE_API_REMOTA: "settings.mysql_connections.engine.api_remota",
    }

    engine = forms.ChoiceField(required=False)

    class Meta:
        model = SettingsMySQLConnection
        fields = [
            'nombre_logico', 'engine', 'host', 'port', 'user', 'password', 'db_name', 'charset', 'is_active'
        ]
        widgets = {
            'password': forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        choices = list(self.ENGINE_CHOICES)

        current_engine = None
        if getattr(self.instance, 'pk', None):
            current_engine = SettingsMySQLConnection.normalize_engine(getattr(self.instance, 'engine', None))
            if current_engine and current_engine not in [c[0] for c in choices]:
                # Compatibilidad hacia atrás: mostrar el engine existente aunque no sea uno de los permitidos
                choices.append((current_engine, current_engine))

        self.fields['engine'].required = False
        self.fields['engine'].choices = choices
        self.fields['engine'].initial = SettingsMySQLConnection.ENGINE_DEFAULT
        self.fields['engine'].widget = EngineSelect(
            choices=choices,
            option_data_keys=self.ENGINE_OPTION_DATA_KEYS,
            attrs={
                'class': 'form-select',
            }
        )

    def clean_nombre_logico(self):
        val = (self.cleaned_data.get('nombre_logico') or '').strip().lower()
        if not re.match(r'^[a-z0-9_]+$', val):
            raise forms.ValidationError('Nombre lógico inválido. Solo letras minúsculas, números y guion bajo.')
        return val

    def clean_engine(self):
        val = SettingsMySQLConnection.normalize_engine(self.cleaned_data.get('engine'))

        # Si el registro ya existía con un engine fuera de catálogo, permitir mantenerlo
        if getattr(self.instance, 'pk', None):
            current_engine = SettingsMySQLConnection.normalize_engine(getattr(self.instance, 'engine', None))
            if val == current_engine and current_engine not in SettingsMySQLConnection.ENGINE_ALLOWED:
                return current_engine

        if val not in SettingsMySQLConnection.ENGINE_ALLOWED:
            raise forms.ValidationError('Engine inválido')

        return val

    def clean_port(self):
        port = self.cleaned_data.get('port')
        if port is None:
            raise forms.ValidationError('Puerto requerido')
        if port <= 0 or port > 65535:
            raise forms.ValidationError('Puerto inválido')
        return port

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.nombre_logico = obj.nombre_logico.strip().lower()
        obj.engine = SettingsMySQLConnection.normalize_engine(getattr(obj, 'engine', None))
        if commit:
            obj.save()
        return obj
