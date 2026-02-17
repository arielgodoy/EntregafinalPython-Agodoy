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
    participantes = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        empresa_id = kwargs.pop('empresa_id', None)
        super().__init__(*args, **kwargs)

        # 1) Base queryset por empresa
        if empresa_id:
            usuario_ids = UsuarioPerfilEmpresa.objects.filter(
                empresa_id=empresa_id,
            ).values_list('usuario_id', flat=True)

            qs = User.objects.filter(
                id__in=usuario_ids,
                is_active=True,
            ).distinct()
        else:
            qs = User.objects.filter(is_active=True)

        # 2) Excluir al usuario actual (para que no puedas seleccionarte)
        if user:
            qs = qs.exclude(id=user.id)

        self.fields['participantes'].queryset = qs

        # 3) IMPORTANTE: NO preseleccionar al usuario actual
        #    (si quieres, puedes dejar vacío o preseleccionar a nadie)
        self.fields['participantes'].initial = []

    class Meta:
        model = Conversacion
        fields = ('participantes',)
