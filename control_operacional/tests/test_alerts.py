from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from control_de_proyectos.models import ClienteEmpresa, Proyecto
from control_operacional.services.alerts import notify_project_created, notify_project_overdue
from notificaciones.models import Notification


class ControlOperacionalAlertsTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.user = User.objects.create_user(username="supervisor", password="pass")
        self.vista = Vista.objects.create(nombre="Control Operacional Dashboard")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        self.cliente = ClienteEmpresa.objects.create(
            nombre="Cliente A",
            rut="12.345.678-5",
        )

    def _create_proyecto(self, nombre="Proyecto A"):
        return Proyecto.objects.create(
            nombre=nombre,
            descripcion="",
            empresa_interna=self.empresa,
            cliente=self.cliente,
            tipo_texto="Consultoria",
        )

    def test_notify_project_created(self):
        proyecto = self._create_proyecto()
        created = notify_project_created(proyecto, self.user)
        self.assertEqual(created, 1)
        self.assertTrue(Notification.objects.filter(
            destinatario=self.user,
            empresa=self.empresa,
            tipo=Notification.Tipo.ALERT,
            titulo="Proyecto creado",
        ).exists())

    def test_notify_project_overdue_dedup(self):
        proyecto = self._create_proyecto(nombre="Proyecto Atrasado")
        proyecto.fecha_termino_estimada = timezone.localdate() - timedelta(days=1)
        proyecto.fecha_termino_real = None
        proyecto.save(update_fields=["fecha_termino_estimada", "fecha_termino_real"])

        first = notify_project_overdue(proyecto, self.user)
        second = notify_project_overdue(proyecto, self.user)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

        self.assertEqual(Notification.objects.filter(
            destinatario=self.user,
            empresa=self.empresa,
            tipo=Notification.Tipo.ALERT,
            titulo="Proyecto atrasado",
        ).count(), 1)
