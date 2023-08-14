# forms.py
from django import forms
from .models import Documento, Propiedad,TipoDocumento,Propietario
from django.contrib.auth.models import User


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ('tipo_documento', 'Nombre_documento', 'propiedad', 'fecha_documento', 'fecha_vencimiento', 'archivo')
        widgets = {
            'fecha_documento': forms.DateInput(attrs={'type': 'date'}),
            'fecha_vencimiento': forms.DateInput(attrs={'type': 'date'}),
        }



class PropietarioForm(forms.ModelForm):
    class Meta:
        model = Propietario
        fields = '__all__'

class PropiedadForm(forms.ModelForm):
    class Meta:
        model = Propiedad
        fields = '__all__'


class TipoDocumentoForm(forms.ModelForm):
    class Meta:
        model = TipoDocumento
        fields = '__all__' 





