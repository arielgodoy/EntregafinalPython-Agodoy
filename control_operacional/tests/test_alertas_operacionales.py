from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from control_de_proyectos.models import ClienteEmpresa, Proyecto
from control_operacional.models import AlertaAck


class ControlOperacionalAlertasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass1234")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(nombre="Control Operacional - Alertas")
        self.vista_ack = Vista.objects.create(nombre="Control Operacional - Reconocer alerta")
        self.cliente = ClienteEmpresa.objects.create(nombre="Cliente A", rut="12.345.678-5")

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _grant_ingresar(self):
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

    def _create_proyecto(self, **kwargs):
        defaults = {
            "nombre": "Proyecto Base",
            "empresa_interna": self.empresa,
            "cliente": self.cliente,
            "tipo_texto": "Operacional",
        }
        defaults.update(kwargs)
        return Proyecto.objects.create(**defaults)

    def test_alertas_generadas_por_reglas(self):
        today = timezone.localdate()

        self._create_proyecto(
            nombre="Proyecto Atrasado",
            fecha_inicio_estimada=today - timedelta(days=30),
            fecha_termino_estimada=today - timedelta(days=1),
            fecha_termino_real=None,
        )
        self._create_proyecto(
            nombre="Proyecto En Riesgo",
            fecha_inicio_estimada=today - timedelta(days=10),
            fecha_termino_estimada=today + timedelta(days=3),
            fecha_termino_real=None,
        )
        self._create_proyecto(
            nombre="Proyecto Sin Fechas",
            fecha_inicio_estimada=None,
            fecha_termino_estimada=None,
        )

        self._login_with_empresa()
        self._grant_ingresar()

        response = self.client.get(reverse("control_operacional:alertas_operacionales"))
        self.assertEqual(response.status_code, 200)

        alertas = response.context.get("alertas")
        self.assertIsNotNone(alertas)
        self.assertEqual(len(alertas), 3)

        severidades = {alerta["severity"] for alerta in alertas}
        self.assertSetEqual(severidades, {"HIGH", "MEDIUM", "LOW"})

    def test_ack_oculta_alerta(self):
        today = timezone.localdate()
        proyecto = self._create_proyecto(
            nombre="Proyecto Atrasado",
            fecha_inicio_estimada=today - timedelta(days=30),
            fecha_termino_estimada=today - timedelta(days=1),
            fecha_termino_real=None,
        )

        self._login_with_empresa()
        self._grant_ingresar()
        # Grant permission for AckAlertaView specifically
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_ack,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        alert_key = f"project:{proyecto.id}:overdue"
        post_response = self.client.post(
            reverse("control_operacional:ack_alerta"),
            {"alert_key": alert_key},
        )
        self.assertEqual(post_response.status_code, 302)

        response = self.client.get(reverse("control_operacional:alertas_operacionales"))
        alertas = response.context.get("alertas")
        keys = {alerta["key"] for alerta in alertas}
        self.assertNotIn(alert_key, keys)

    def test_ack_rechaza_key_invalida(self):
        self._login_with_empresa()
        self._grant_ingresar()
        # Grant permission for AckAlertaView specifically
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_ack,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        response = self.client.post(
            reverse("control_operacional:ack_alerta"),
            {"alert_key": "project:999:inventada"},
        )
        self.assertEqual(response.status_code, 400)

    def test_scoping_empresa(self):
        empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        cliente_b = ClienteEmpresa.objects.create(nombre="Cliente B", rut="76.543.210-3")
        today = timezone.localdate()

        self._create_proyecto(
            nombre="Proyecto Empresa A",
            fecha_inicio_estimada=today - timedelta(days=10),
            fecha_termino_estimada=today - timedelta(days=1),
            fecha_termino_real=None,
        )
        Proyecto.objects.create(
            nombre="Proyecto Empresa B",
            empresa_interna=empresa_b,
            cliente=cliente_b,
            tipo_texto="Operacional",
            fecha_inicio_estimada=today - timedelta(days=5),
            fecha_termino_estimada=today - timedelta(days=1),
            fecha_termino_real=None,
        )

        self._login_with_empresa()
        self._grant_ingresar()

        response = self.client.get(reverse("control_operacional:alertas_operacionales"))
        alertas = response.context.get("alertas")
        nombres = {alerta["proyecto_nombre"] for alerta in alertas}
        self.assertIn("Proyecto Empresa A", nombres)
        self.assertNotIn("Proyecto Empresa B", nombres)

    def test_alerta_ack_unica_por_usuario_empresa(self):
        today = timezone.localdate()
        proyecto = self._create_proyecto(
            nombre="Proyecto Atrasado",
            fecha_inicio_estimada=today - timedelta(days=30),
            fecha_termino_estimada=today - timedelta(days=1),
            fecha_termino_real=None,
        )

        AlertaAck.objects.create(
            empresa=self.empresa,
            user=self.user,
            alert_key=f"project:{proyecto.id}:overdue",
        )

        with self.assertRaises(IntegrityError):
            AlertaAck.objects.create(
                empresa=self.empresa,
                user=self.user,
                alert_key=f"project:{proyecto.id}:overdue",
            )
