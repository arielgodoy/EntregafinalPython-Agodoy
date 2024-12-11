from django.db import models
from biblioteca.models import Propietario
# Create your models here.
class Company(models.Model):
    name = models.CharField(max_length=50)
    website = models.URLField(max_length=100)
    foundation = models.PositiveIntegerField()
class Ciudad(models.Model):
    nombre = models.CharField(max_length=100)
    def __str__(self):
        return self.nombre

class Persona(models.Model):
    nombre = models.CharField(max_length=100)
    edad = models.PositiveIntegerField()
    ciudad = models.ForeignKey(Ciudad, on_delete=models.CASCADE)

    def __str__(self):
        return self.nombre
