from django.core.exceptions import ValidationError
from django.db import models

from .services.rut import normalizar_rut, validar_rut


class Proveedor(models.Model):
	rut = models.CharField(max_length=12, null=True, blank=True, unique=True)
	nombre = models.CharField(max_length=255)
	direccion = models.CharField(max_length=255, blank=True, default="")
	comuna = models.CharField(max_length=100, blank=True, default="")
	ciudad = models.CharField(max_length=100, blank=True, default="")
	fono1 = models.CharField(max_length=30, blank=True, default="")
	fono2 = models.CharField(max_length=30, blank=True, default="")
	fax = models.CharField(max_length=30, blank=True, default="")
	contacto = models.CharField(max_length=150, blank=True, default="")
	email1 = models.EmailField(blank=True, default="")
	email2 = models.EmailField(blank=True, default="")
	activo = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["nombre", "id"]

	def clean(self):
		self.nombre = self.nombre.strip() if self.nombre else ""
		if not self.nombre:
			raise ValidationError({"nombre": "El nombre es obligatorio."})

		for field_name in (
			"direccion",
			"comuna",
			"ciudad",
			"fono1",
			"fono2",
			"fax",
			"contacto",
			"email1",
			"email2",
		):
			value = getattr(self, field_name)
			setattr(self, field_name, value.strip() if value else "")

		try:
			self.rut = normalizar_rut(self.rut)
			validar_rut(self.rut)
		except ValidationError as error:
			raise ValidationError({"rut": error.messages}) from error

	def save(self, *args, **kwargs):
		self.nombre = self.nombre.strip() if self.nombre else ""
		self.rut = normalizar_rut(self.rut)
		self.full_clean()
		return super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.nombre} ({self.rut})" if self.rut else self.nombre
