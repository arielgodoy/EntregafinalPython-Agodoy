import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Vista, Permiso
from control_de_proyectos.models import ClienteEmpresa, Proyecto, Tarea


class AvancePermisosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user1', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista = Vista.objects.create(nombre='Control de Proyectos - Actualizar avance de tarea')
        self.cliente = ClienteEmpresa.objects.create(
            nombre='Cliente Uno',
            rut='12.345.678-5',
            telefono='123',
            email='cliente@example.com',
            direccion='Calle 123',
            ciudad='Santiago'
        )
        self.proyecto = Proyecto.objects.create(
            nombre='Proyecto A',
            descripcion='Desc',
            empresa_interna=self.empresa,
            cliente=self.cliente,
            tipo_texto='Tipo'
        )
        self.tarea = Tarea.objects.create(
            proyecto=self.proyecto,
            nombre='Tarea 1'
        )

    def _login_with_empresa(self):
        self.client.login(username='user1', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_post_sin_permiso_devuelve_403(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            modificar=False
        )
        self._login_with_empresa()
        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 10}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

    def test_post_con_permiso_actualiza_avance(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            modificar=True
        )
        self._login_with_empresa()
        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 30}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.porcentaje_avance, 30)
