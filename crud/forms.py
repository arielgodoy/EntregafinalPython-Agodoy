from django import forms
from django.forms import ModelForm
from .models import Documento,Propiedades,Propietario
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class DocForm(ModelForm):
    class Meta:
        model = Documento
        fields = '__all__'
class BuscaDocs(forms.Form):
    titulo = forms.CharField(max_length=100,required=False)


class PropForm(ModelForm):
    class Meta:
        model = Propiedades
        fields = '__all__'
class BuscaProps(forms.Form):
    rol = forms.CharField(max_length=10,required=False)

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
 
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        # Saca los mensajes de ayuda
        help_texts = {k:"" for k in fields}

class UserEditform(UserCreationForm):
    email = forms.EmailField(label="Modificar E-mail")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
 
    class Meta:
        model = User
        fields = ['email', 'password1', 'password2']
        # Saca los mensajes de ayuda
        help_texts = {k:"" for k in fields}


class PropietarioForm(ModelForm):
    class Meta:
        model = Propietario
        fields = '__all__'
class BuscaPropietario(forms.Form):
    nombre = forms.CharField(max_length=100,required=False)