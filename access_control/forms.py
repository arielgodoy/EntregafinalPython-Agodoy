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