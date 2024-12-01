from django.db import models
from ckeditor.fields import RichTextField  
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


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
    rut = models.CharField(max_length=20, unique=True)
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
    
def validate_file_extension(value):
    if not value.name.lower().endswith(('.pdf', '.jpeg', '.jpg', '.png', '.dwg')):
        raise ValidationError(_('Formato de archivo no admitido. Sube un PDF, JPEG, JPG, PNG o DWG.'))


class Documento(models.Model):
    TIPOS_ARCHIVO = (
        ('pdf', 'PDF'),
        ('jpeg', 'JPEG'),
        ('dwg', 'DWG'),
    )    
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.CASCADE)
    nombre_documento = models.CharField(max_length=50)
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE)
    archivo = models.FileField(upload_to='archivos_documentos/', validators=[validate_file_extension])
    fecha_documento = models.DateField(default=timezone.now)
    fecha_vencimiento = models.DateField(null=True, blank=True)  # Fecha de vencimiento puede ser nula

    def __str__(self):
        return f"{self.tipo_documento} - {self.propiedad.rol}"



