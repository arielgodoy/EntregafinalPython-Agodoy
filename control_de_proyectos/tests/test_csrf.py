import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Vista, Permiso
from control_de_proyectos.models import ClienteEmpresa, Proyecto, Tarea


class AvanceCsrfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user3', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista_modificar = Vista.objects.create(nombre='Control de Proyectos - Actualizar avance de tarea')
        self.vista_detalle = Vista.objects.create(nombre='Control de Proyectos - Detalle de proyecto')

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

        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_modificar,
            modificar=True
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_detalle,
            ingresar=True
        )

        self.client = Client(enforce_csrf_checks=True)
        self.client.login(username='user3', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_post_sin_csrf_devuelve_403(self):
        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 10}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

    def test_post_con_csrf_devuelve_200(self):
        detalle_url = reverse('control_de_proyectos:detalle_proyecto', args=[self.proyecto.id])
        response = self.client.get(detalle_url)
        csrf_token = response.cookies.get('csrftoken').value

        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 25}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(response.status_code, 200)
