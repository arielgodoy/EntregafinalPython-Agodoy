# forms.py
from django import forms
from .models import Documento, Propiedad,TipoDocumento,Propietario
from django.contrib.auth.models import User


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ('tipo_documento', 'Nombre_documento','propiedad', 'archivo')

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





