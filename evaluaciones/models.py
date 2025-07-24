from django.db import models
from datetime import datetime

class Persona(models.Model):
    person_id = models.IntegerField(unique=True)
    full_name = models.CharField(max_length=255)
    first_name = models.CharField(max_length=100)
    surname = models.CharField(max_length=100)
    second_surname = models.CharField(max_length=100, blank=True, null=True)
    document_type = models.CharField(max_length=20)
    document_number = models.CharField(max_length=20)
    rut = models.CharField(max_length=20)
    code_sheet = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    personal_email = models.EmailField(blank=True, null=True)
    address = models.CharField(max_length=255)
    street = models.CharField(max_length=100)
    street_number = models.CharField(max_length=20)
    office_number = models.CharField(max_length=20, blank=True, null=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    location_id = models.IntegerField(blank=True, null=True)
    region = models.CharField(max_length=100)
    office_phone = models.CharField(max_length=50, blank=True, null=True)
    phone = models.CharField(max_length=50)
    gender = models.CharField(max_length=1)
    birthday = models.DateField()
    active_since = models.DateField()
    created_at = models.DateTimeField()
    status = models.CharField(max_length=20)
    payment_method = models.CharField(max_length=50)
    payment_period = models.CharField(max_length=20)
    advance_payment = models.CharField(max_length=50)
    bank = models.CharField(max_length=50)
    account_type = models.CharField(max_length=50)
    account_number = models.CharField(max_length=50)
    private_role = models.BooleanField(default=False)
    progressive_vacations_start = models.DateField()
    nationality = models.CharField(max_length=50)
    country_code = models.CharField(max_length=10)
    civil_status = models.CharField(max_length=50)
    health_company = models.CharField(max_length=50)
    pension_regime = models.CharField(max_length=50)
    pension_fund = models.CharField(max_length=50)
    afc = models.CharField(max_length=20)
    retired = models.BooleanField(default=False)

    mes = models.PositiveSmallIntegerField(default=datetime.now().month)
    anio = models.PositiveSmallIntegerField(default=datetime.now().year)

    class Meta:
        verbose_name = "Persona"
        verbose_name_plural = "Personas"
        ordering = ['-anio', '-mes', 'full_name']

    def __str__(self):
        return self.full_name
