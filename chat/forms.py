# forms.py
from django import forms
from .models import Mensaje, Conversacion
from django.contrib.auth.models import User

from access_control.models import UsuarioPerfilEmpresa
class MensajeForm(forms.ModelForm):
    class Meta:
        model = Mensaje
        fields = ('contenido',)

class EnviarMensajeForm(forms.Form):
    contenido = forms.CharField(label="Mensaje", widget=forms.Textarea(attrs={'rows': 1, 'cols': 85}))

class ConversacionForm(forms.ModelForm):
    participantes = forms.ModelMultipleChoiceField(queryset=User.objects.all(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        empresa_id = kwargs.pop('empresa_id', None)
        super().__init__(*args, **kwargs)        
        if empresa_id:
            usuario_ids = UsuarioPerfilEmpresa.objects.filter(
                empresa_id=empresa_id,
            ).values_list('usuario_id', flat=True)
            self.fields['participantes'].queryset = User.objects.filter(
                id__in=usuario_ids,
                is_active=True,
            ).distinct()
        else:
            self.fields['participantes'].queryset = User.objects.filter(is_active=True)

        if user:
            self.fields['participantes'].initial = [user.id]

    class Meta:
        model = Conversacion
        fields = ('participantes',)