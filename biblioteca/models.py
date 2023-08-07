from django.db import models
from ckeditor.fields import RichTextField  


class TipoDocumento(models.Model):
    nombre = models.CharField(max_length=100)
    descricion = RichTextField(default='',null=True)

    def __str__(self):
        return self.nombre

class Propietario(models.Model):
    ROL_CHOICES = (
        ('persona', 'Persona Natural'),
        ('sociedad', 'Sociedad'),
    )
    nombre = models.CharField(max_length=100)
    rut = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    def __str__(self):
        return self.nombre

class Propiedad(models.Model):
    rol = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    ciudad = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
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
    Nombre_documento = models.CharField(max_length=100)
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE)
    archivo = models.FileField(upload_to='archivos_documentos/')
    def __str__(self):
        return f"{self.tipo_documento} - {self.propiedad.rol}"



