from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from acounts.models import SystemConfig, EmailAccount, CompanyConfig
from .models import Permiso, Empresa
from django.contrib.auth.models import User

class PermisoForm(forms.ModelForm):
    class Meta:
        model = Permiso
        fields = ['usuario', 'empresa', 'vista', 'ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
        widgets = {
            'ingresar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'crear': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'modificar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'eliminar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'autorizar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'supervisor': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class PermisoFiltroForm(forms.Form):
    usuario = forms.ModelChoiceField(queryset=User.objects.all(), required=False, label="Usuario")
    empresa = forms.ModelChoiceField(queryset=Empresa.objects.all(), required=False, label="Empresa")

    def clean_usuario(self):
        usuario = self.cleaned_data.get('usuario')
        print("Usuario validado:", usuario)
        return usuario

    def clean_empresa(self):
        empresa = self.cleaned_data.get('empresa')
        print("Empresa validada:", empresa)
        return empresa






class UsuarioCrearForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Contraseña"
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Confirmar Contraseña"
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control'})
        self.fields['email'].widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class UsuarioInvitacionForm(forms.Form):
    TIPO_USUARIO_CHOICES = [
        ('PROFESIONAL', 'Profesional'),
        ('USUARIO', 'Usuario'),
    ]

    email = forms.EmailField(
        label="Email",
        error_messages={
            'required': 'validation.email_required',
            'invalid': 'validation.email_invalid',
        },
    )
    first_name = forms.CharField(label="Nombre", required=False)
    last_name = forms.CharField(label="Apellido", required=False)
    tipo_usuario = forms.ChoiceField(label="Tipo de usuario", choices=TIPO_USUARIO_CHOICES, initial='USUARIO')
    usuario_referencia = forms.ModelChoiceField(
        label="Copiar desde usuario",
        queryset=User.objects.none(),
        required=False,
    )
    empresas = forms.ModelMultipleChoiceField(
        queryset=Empresa.objects.all(),
        required=False,
        label="Empresas",
    )

    def __init__(self, *args, **kwargs):
        empresa_in_session = kwargs.pop('empresa_in_session', None)
        super().__init__(*args, **kwargs)
        self.empresa_in_session = empresa_in_session
        self.fields['email'].widget.attrs.update({'class': 'form-control'})
        self.fields['first_name'].widget.attrs.update({'class': 'form-control'})
        self.fields['last_name'].widget.attrs.update({'class': 'form-control'})
        self.fields['tipo_usuario'].widget.attrs.update({'class': 'form-control'})
        self.fields['usuario_referencia'].widget.attrs.update({'class': 'form-control'})
        self.fields['empresas'].widget.attrs.update({'class': 'form-select'})

        empresa_ids = []
        if self.data:
            empresa_ids = self.data.getlist('empresas')

        if not empresa_ids and empresa_in_session is not None:
            empresa_ids = [str(empresa_in_session.pk)]

        if empresa_ids:
            self.fields['usuario_referencia'].queryset = User.objects.filter(
                permiso__empresa_id__in=empresa_ids,
                is_active=True,
            ).distinct().order_by('username')

        if empresa_in_session is not None:
            self.fields['empresas'].initial = [empresa_in_session.pk]

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError('validation.email_required')
        return email

    def clean(self):
        cleaned_data = super().clean()
        tipo_usuario = cleaned_data.get('tipo_usuario')
        usuario_referencia = cleaned_data.get('usuario_referencia')
        empresas = list(cleaned_data.get('empresas') or [])

        if not empresas:
            empresa_in_session = getattr(self, 'empresa_in_session', None)
            if empresa_in_session:
                empresas = [empresa_in_session]
                cleaned_data['empresas'] = empresas
            else:
                self.add_error('empresas', 'validation.company_required')

        if tipo_usuario == 'USUARIO' and not usuario_referencia:
            self.add_error('usuario_referencia', 'validation.reference_required')

        if tipo_usuario == 'PROFESIONAL':
            cleaned_data['usuario_referencia'] = None

        if tipo_usuario == 'USUARIO' and usuario_referencia and empresas:
            empresa_ids = [empresa.id for empresa in empresas]
            tiene_permiso = Permiso.objects.filter(
                usuario=usuario_referencia,
                empresa_id__in=empresa_ids,
            ).exists()
            if not tiene_permiso:
                self.add_error(
                    'usuario_referencia',
                    'validation.reference_company_mismatch'
                )

        return cleaned_data


class SystemConfigForm(forms.ModelForm):
    class Meta:
        model = SystemConfig
        fields = [
            'public_base_url',
            'default_from_email',
            'default_from_name',
            'security_email_account',
            'notifications_email_account',
            'alerts_email_account',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        self.fields['public_base_url'].required = True

    def clean_public_base_url(self):
        value = (self.cleaned_data.get('public_base_url') or '').strip()
        if not value:
            raise ValidationError('public_base_url es obligatorio.')
        return value


class EmailAccountForm(forms.ModelForm):
    class Meta:
        model = EmailAccount
        fields = [
            'name',
            'from_email',
            'from_name',
            'smtp_host',
            'smtp_port',
            'smtp_user',
            'smtp_password',
            'use_tls',
            'use_ssl',
            'reply_to',
            'is_active',
        ]
        widgets = {
            'smtp_password': forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input form-control'})
            else:
                field.widget.attrs.update({'class': 'form-control'})
        if self.instance and self.instance.pk:
            self.fields['smtp_password'].required = False

    def clean_smtp_password(self):
        value = self.cleaned_data.get('smtp_password')
        if self.instance and self.instance.pk:
            if not value:
                return self.instance.smtp_password
        if not value:
            raise ValidationError('smtp_password es obligatorio.')
        return value


class CompanyConfigForm(forms.ModelForm):
    class Meta:
        model = CompanyConfig
        fields = [
            'public_base_url',
            'from_name',
            'from_email',
            'security_email_account',
            'notifications_email_account',
            'alerts_email_account',
            'activation_ttl_hours',
            'reset_ttl_minutes',
            'max_failed_logins',
            'lock_minutes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class UsuarioEditarForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Contraseña",
        required=False
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data['password']:
            user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user
