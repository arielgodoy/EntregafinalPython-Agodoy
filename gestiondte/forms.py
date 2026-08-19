from django import forms
import os
from .models import CertificadoSII
from .utils.maestro import get_maestroempresa_by_codigo
from .services.rpetc import RPETCParameterError, validar_parametros_cesiones


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
        instance.updated_by = user
        if commit:
            instance.save()
        return instance


class SincronizarCesionesRPETCForm(forms.Form):
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
