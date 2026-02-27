from django import forms
from .models import SettingsMySQLConnection
import re


class SettingsMySQLConnectionForm(forms.ModelForm):
    class Meta:
        model = SettingsMySQLConnection
        fields = [
            'nombre_logico', 'engine', 'host', 'port', 'user', 'password', 'db_name', 'charset', 'is_active'
        ]
        widgets = {
            'password': forms.PasswordInput(render_value=True),
        }

    def clean_nombre_logico(self):
        val = (self.cleaned_data.get('nombre_logico') or '').strip().lower()
        if not re.match(r'^[a-z0-9_]+$', val):
            raise forms.ValidationError('Nombre lógico inválido. Solo letras minúsculas, números y guion bajo.')
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
        if commit:
            obj.save()
        return obj
