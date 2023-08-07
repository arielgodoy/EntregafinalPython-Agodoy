# forms.py
from django import forms
from .models import Mensaje, Conversacion
from django.contrib.auth.models import User
class MensajeForm(forms.ModelForm):
    class Meta:
        model = Mensaje
        fields = ('contenido',)

class EnviarMensajeForm(forms.Form):
    contenido = forms.CharField(label="Mensaje", widget=forms.Textarea(attrs={'rows': 1, 'cols': 85}))

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