from django.db import models
from ckeditor.fields import RichTextField  
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

import os
from django.utils.timezone import now

def validar_rut(rut):
    rut = rut.upper().replace(".", "").replace("-", "")
    cuerpo, dv = rut[:-1], rut[-1]

    suma = sum(int(cuerpo[::-1][i]) * (2 + i % 6) for i in range(len(cuerpo)))
    dv_esperado = 11 - (suma % 11)
    dv_esperado = '0' if dv_esperado == 11 else 'K' if dv_esperado == 10 else str(dv_esperado)

    if dv != dv_esperado:
        raise ValidationError(_("RUT inválido: dígito verificador incorrecto"))

def archivo_documento_path(instance, filename):
    """
    Función para generar la ruta del archivo.
    Reemplaza caracteres conflictivos como '/' en el rol de la propiedad.
    """
    # Reemplazar '/' por '-' en el rol de la propiedad
    rol_sanitizado = instance.propiedad.rol.replace("/", "-")

    # Extraer la extensión del archivo original
    extension = os.path.splitext(filename)[1]

    # Crear el nombre del archivo
    nuevo_nombre = f"{rol_sanitizado}_{instance.tipo_documento}_{instance.nombre_documento}{extension}"

    # Crear la ruta dentro de la carpeta `archivos_documentos`
    return f"archivos_documentos/{nuevo_nombre}"

def validate_file_extension(value):
    if not value.name.lower().endswith(('.pdf', '.jpeg', '.jpg', '.png', '.dwg', '.rar', '.zip')):
        raise ValidationError(_('Formato de archivo no admitido. Sube un PDF, JPEG, JPG, PNG o DWG.'))

class TipoDocumento(models.Model):
    nombre = models.CharField(max_length=50)
    descricion = RichTextField(default='',null=True)

    def __str__(self):
        return self.nombre

class Propietario(models.Model):
    ROL_CHOICES = (
        ('persona', 'Persona Natural'),
        ('sociedad', 'Sociedad'),
    )
    nombre = models.CharField(max_length=50)
    rut = models.CharField(max_length=20, unique=True, validators=[validar_rut])
    telefono = models.CharField(max_length=20)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    def __str__(self):
        return self.nombre

class Propiedad(models.Model):    
    rol = models.CharField(max_length=20)
    descripcion = models.CharField(default='',max_length=50)    
    direccion = models.CharField(default='',max_length=50)
    ciudad = models.CharField(max_length=100)
    telefono = models.CharField(default='452379500',max_length=20)
    propietario = models.ForeignKey(Propietario, on_delete=models.CASCADE)
    def __str__(self):
        return self.rol
    



class Documento(models.Model):
    TIPOS_ARCHIVO = (
        ('pdf', 'PDF'),
        ('jpeg', 'JPEG'),
        ('dwg', 'DWG'),
    )    
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.CASCADE)
    nombre_documento = models.CharField(max_length=50)
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE)
    archivo = models.FileField(upload_to=archivo_documento_path, validators=[validate_file_extension])
    fecha_documento = models.DateField(default=now)
    fecha_vencimiento = models.DateField(null=True, blank=True)  # Fecha de vencimiento puede ser nula

    def __str__(self):
        return f"{self.tipo_documento} - {self.propiedad.rol}"



