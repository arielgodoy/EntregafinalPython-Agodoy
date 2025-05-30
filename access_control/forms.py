from django import forms
from .models import Permiso,Empresa
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
