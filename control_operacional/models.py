from django.db import models
from access_control.models import Empresa


class RegistroOperacional(models.Model):
	empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='registros_operacionales')
	titulo = models.CharField(max_length=150)
	creado_en = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-creado_en']
		verbose_name = 'Registro Operacional'
		verbose_name_plural = 'Registros Operacionales'

	def __str__(self):
		return self.titulo
