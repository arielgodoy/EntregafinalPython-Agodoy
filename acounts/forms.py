# forms.py
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Avatar
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UserChangeForm
#from .models import CustomUser
from django.forms import ModelForm
from django.contrib.auth.models import User


class CustomUserForm(UserChangeForm):
     class Meta:
         #model = CustomUser
         model = User
         fields = ['username', 'first_name', 'last_name', 'email']

class AvatarForm(ModelForm):
     imagen= forms.ImageField(required=False)
     class Meta:
        model = Avatar
        fields = ['imagen', 'profesion', 'dni', 'first_name', 'last_name', 'email']
        labels = {                        
                        'first_name':'Nombre',
                        'last_name': 'Apellido ',
                        'email': 'Correo electronico',
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
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            raise ValidationError('Las contraseñas no coinciden.')

        if password1:
            validate_password(password1)

        return cleaned_data

    def save(self, user):
        user.set_password(self.cleaned_data['password1'])
        return user





