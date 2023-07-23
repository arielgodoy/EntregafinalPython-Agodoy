from django import forms
from django.forms import ModelForm
from .models import Documento,Propiedades,Propietario,Avatar
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm  
from .models import Mensaje, Conversacion

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
    username = forms.CharField(label="Usuario")
    email = forms.EmailField()
    first_name = forms.CharField(label="Nombre")
    last_name = forms.CharField(label="Apellido")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
 
    class Meta:
        model = User        
        fields = ['username','email','first_name', 'last_name','password1', 'password2']
        # Saca los mensajes de ayuda
        help_texts = {k:"" for k in fields}

class UserEditform(UserCreationForm):  
    
    email = forms.EmailField()
    first_name = forms.CharField(label="Nombre")
    last_name = forms.CharField(label="Apellido")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
    
    class Meta:
        model = User
        fields = ['email','first_name', 'last_name','password1', 'password2']
        # Saca los mensajes de ayuda
        help_texts = {k:"" for k in fields}


class PropietarioForm(ModelForm):
    class Meta:
        model = Propietario
        fields = '__all__'
class BuscaPropietario(forms.Form):
    nombre = forms.CharField(max_length=100,required=False)



class AvatarForm(ModelForm):
    imagen= forms.ImageField(required=False)
    class Meta:
        model = Avatar
        fields = ['imagen']
        



class MensajeForm(forms.ModelForm):
    class Meta:
        model = Mensaje
        fields = ('contenido',)

class EnviarMensajeForm(forms.Form):
    contenido = forms.CharField(label="Contenido", widget=forms.Textarea(attrs={'rows': 4, 'cols': 40}))

class ConversacionForm(forms.ModelForm):
    participantes = forms.ModelMultipleChoiceField(queryset=User.objects.all(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)        
        self.fields['participantes'].queryset = User.objects.all()
        self.fields['participantes'].initial = [user.id]  

    class Meta:
        model = Conversacion
        fields = ('participantes',)