# forms.py
from django import forms
from .models import Documento, Propiedad,TipoDocumento,Propietario
from django.contrib.auth.models import User
import re

class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['tipo_documento', 'nombre_documento', 'propiedad', 'fecha_documento', 'fecha_vencimiento', 'archivo']
        widgets = {
            'fecha_documento': forms.DateInput(attrs={'type': 'date'}),
            'fecha_vencimiento': forms.DateInput(attrs={'type': 'date'}),
            'propiedad': forms.HiddenInput(),  # Ocultar el campo propiedad
        }


class PropietarioForm(forms.ModelForm):
    class Meta:
        model = Propietario
        fields = ['nombre', 'rut', 'telefono', 'rol']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'rut': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
        }
    def clean_rut(self):
        rut = self.cleaned_data['rut']
        pattern = r'^\d{1,2}\.\d{3}\.\d{3}-[\dkK]$'  # Regex para el formato RUT
        if not re.match(pattern, rut):
            raise forms.ValidationError("El RUT debe tener el formato XX.XXX.XXX-X.")
        return rut

class PropiedadForm(forms.ModelForm):
    class Meta:
        model = Propiedad
        fields = '__all__'  # Asegúrate de incluir todos los campos
        widgets = {
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class TipoDocumentoForm(forms.ModelForm):
    class Meta:
        model = TipoDocumento
        fields = '__all__' 





