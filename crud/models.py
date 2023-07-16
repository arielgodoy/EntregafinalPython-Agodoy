from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Avatar(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,null=True)
    imagen = models.ImageField(default='default.jpg',upload_to='avatares',null = True, blank=True)
    def __str__(self):
        return f'{self.user} {self.imagen}'


class Documento(models.Model):
    titulo = models.CharField(db_column='titulo', max_length=100, blank=False)
    descripcion = models.CharField(db_column='descripcion', max_length=100, blank=False)
    autor = models.CharField(db_column='autor', max_length=100, blank=False)
    anio = models.IntegerField(db_column='anio', blank=False, default=2023)
    
    def __str__(self):
        return f"Documento: {self.titulo}, {self.descripcion}, {self.autor}, {self.anio}"

class Propiedades(models.Model):
    rol = models.CharField(db_column='rol', max_length=10, blank=False)
    direccion = models.CharField(db_column='direccion', max_length=100, blank=False)
    rut = models.CharField(db_column='rut', blank=False, max_length=10, default='111111111')
    
    def __str__(self):
        return f"Propiedades: {self.rol}, {self.direccion}, {self.rut}"

class Propietario(models.Model):
    nombre = models.CharField(db_column='nombre', max_length=100, blank=False)
    direccion = models.CharField(db_column='direccion', max_length=100, blank=False)
    fono = models.CharField(db_column='fono', blank=False, max_length=10, default='5695555555')
    
    def __str__(self):
        return f"Propietario: {self.nombre}, {self.direccion}, {self.fono}"
    






class Conversacion(models.Model):
    participantes = models.ManyToManyField(User, related_name='conversaciones')

    def __str__(self):
        return ', '.join([str(participante) for participante in self.participantes.all()])

class Mensaje(models.Model):
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    remitente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_enviados')
    contenido = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.remitente}: {self.contenido}'