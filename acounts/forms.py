# forms.py
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Avatar
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.forms import UserChangeForm
#from .models import CustomUser
from django.forms import ModelForm
from django.contrib.auth.models import User


# Longitud minima exigida para contrasenas nuevas (activacion y cambio desde perfil).
STRONG_PASSWORD_MIN_LENGTH = 12


class CustomUserForm(UserChangeForm):
     class Meta:
         #model = CustomUser
         model = User
         fields = ['username', 'first_name', 'last_name', 'email']
     
     def __init__(self, *args, **kwargs):
         super().__init__(*args, **kwargs)
         # Hacer el campo username de solo lectura
         self.fields['username'].disabled = True
         self.fields['username'].widget.attrs.update({
             'class': 'form-control',
             'readonly': 'readonly'
         })

class AvatarForm(ModelForm):
     imagen= forms.ImageField(required=False)
     class Meta:
        model = Avatar
        fields = ['imagen', 'profesion', 'dni']
        labels = {                        
                        'profesion': 'Profesión Usuario',
                        'dni': 'RUT/DNI'
                }
        


class CustomLoginForm(AuthenticationForm):
    # Aquí puedes agregar campos personalizados si los necesitas
    # Por ejemplo: campo de recordar contraseña, campo de captcha, etc.
    # Puedes personalizar las etiquetas de los campos y atributos de widgets
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Usuario'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Contraseña'}))


class ActivationPasswordForm(forms.Form):
    ACTIVATION_MIN_LENGTH = STRONG_PASSWORD_MIN_LENGTH

    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1 and len(password1) < self.ACTIVATION_MIN_LENGTH:
            raise ValidationError(
                'La contraseña debe tener al menos %(min_length)d caracteres.',
                params={'min_length': self.ACTIVATION_MIN_LENGTH},
            )
        return password1

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            raise ValidationError('Las contraseñas no coinciden.')

        if password1:
            validate_password(password1, user=self.user)

        return cleaned_data

    def save(self, user):
        user.set_password(self.cleaned_data['password1'])
        return user


class AccountPasswordChangeForm(PasswordChangeForm):
    """PasswordChangeForm nativo + minimo de caracteres propio de este proyecto."""

    MIN_LENGTH = STRONG_PASSWORD_MIN_LENGTH

    def clean_new_password1(self):
        password1 = self.cleaned_data.get('new_password1')
        if password1 and len(password1) < self.MIN_LENGTH:
            raise ValidationError(
                'La nueva contraseña debe tener al menos %(min_length)d caracteres.',
                params={'min_length': self.MIN_LENGTH},
                code='password_too_short',
            )
        return password1





