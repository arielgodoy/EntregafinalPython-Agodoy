from django.db import IntegrityError, transaction
from django.test import TestCase

from access_control.models import Empresa
from control_de_proyectos.models import ClienteEmpresa, Proyecto


class ProyectoModelTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.cliente = ClienteEmpresa.objects.create(
            nombre='Cliente Uno',
            rut='12.345.678-5',
            telefono='123',
            email='cliente@example.com',
            direccion='Calle 123',
            ciudad='Santiago'
        )

    def test_unique_together_nombre_empresa_cliente(self):
        Proyecto.objects.create(
            nombre='Proyecto A',
            descripcion='Desc',
            empresa_interna=self.empresa,
            cliente=self.cliente,
            tipo_texto='Tipo'
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Proyecto.objects.create(
                    nombre='Proyecto A',
                    descripcion='Desc',
                    empresa_interna=self.empresa,
                    cliente=self.cliente,
                    tipo_texto='Tipo'
                )
