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


class AlertaAck(models.Model):
	empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='alertas_ack')
	user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='alertas_ack')
	alert_key = models.CharField(max_length=200)
	acknowledged_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['empresa', 'user', 'alert_key'], name='uniq_alerta_ack'),
		]

	def __str__(self):
		return f"{self.user_id}:{self.empresa_id}:{self.alert_key}"
