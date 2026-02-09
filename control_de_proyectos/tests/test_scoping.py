from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Vista, Permiso
from control_de_proyectos.models import ClienteEmpresa, Proyecto


class ProyectosScopingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user2', password='pass')
        self.empresa_a = Empresa.objects.create(codigo='01', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='02', descripcion='Empresa B')
        self.vista = Vista.objects.create(nombre='Listar Proyectos')

        self.cliente_a = ClienteEmpresa.objects.create(
            nombre='Cliente A',
            rut='12.345.678-5',
            telefono='123',
            email='clientea@example.com',
            direccion='Calle 1',
            ciudad='Santiago'
        )
        self.cliente_b = ClienteEmpresa.objects.create(
            nombre='Cliente B',
            rut='9.876.543-3',
            telefono='456',
            email='clienteb@example.com',
            direccion='Calle 2',
            ciudad='Santiago'
        )

        self.proyecto_a = Proyecto.objects.create(
            nombre='Proyecto A',
            descripcion='Desc',
            empresa_interna=self.empresa_a,
            cliente=self.cliente_a,
            tipo_texto='Tipo'
        )
        self.proyecto_b = Proyecto.objects.create(
            nombre='Proyecto B',
            descripcion='Desc',
            empresa_interna=self.empresa_b,
            cliente=self.cliente_b,
            tipo_texto='Tipo'
        )

        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=self.vista,
            ingresar=True
        )

    def test_listado_filtra_por_empresa_activa(self):
        self.client.login(username='user2', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa_a.id
        session.save()

        url = reverse('control_de_proyectos:listar_proyectos')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        proyectos = list(response.context['proyectos'])
        self.assertIn(self.proyecto_a, proyectos)
        self.assertNotIn(self.proyecto_b, proyectos)
