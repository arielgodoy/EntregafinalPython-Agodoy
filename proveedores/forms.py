from django import forms

from .models import Proveedor


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = [
            "rut",
            "nombre",
            "direccion",
            "comuna",
            "ciudad",
            "fono1",
            "fono2",
            "fax",
            "contacto",
            "email1",
            "email2",
        ]
        widgets = {
            "rut": forms.TextInput(attrs={"class": "form-control", "maxlength": 12}),
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "direccion": forms.TextInput(attrs={"class": "form-control"}),
            "comuna": forms.TextInput(attrs={"class": "form-control"}),
            "ciudad": forms.TextInput(attrs={"class": "form-control"}),
            "fono1": forms.TextInput(attrs={"class": "form-control"}),
            "fono2": forms.TextInput(attrs={"class": "form-control"}),
            "fax": forms.TextInput(attrs={"class": "form-control"}),
            "contacto": forms.TextInput(attrs={"class": "form-control"}),
            "email1": forms.EmailInput(attrs={"class": "form-control"}),
            "email2": forms.EmailInput(attrs={"class": "form-control"}),
        }
