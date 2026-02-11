from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from chat.models import Conversacion, Mensaje
from notificaciones.models import DemoSeedLog, Notification


@override_settings(MIGRATION_MODULES={})
class TestSeedDemoComms(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.perfil = PerfilAcceso.objects.create(nombre="Demo", descripcion="Demo")
        user_model = get_user_model()
        self.user_a = user_model.objects.create_user(
            username="demo_a",
            email="demo_a@demo.local",
            password="demo12345",
        )
        self.user_b = user_model.objects.create_user(
            username="demo_b",
            email="demo_b@demo.local",
            password="demo12345",
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=self.user_a,
            empresa=self.empresa,
            perfil=self.perfil,
            asignado_por=None,
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=self.user_b,
            empresa=self.empresa,
            perfil=self.perfil,
            asignado_por=None,
        )

    def test_seed_and_reset(self):
        out = StringIO()
        call_command(
            "seed_demo_comms",
            empresa=self.empresa.id,
            users=2,
            convs=1,
            msgs=2,
            notifs=1,
            stdout=out,
        )
        log = DemoSeedLog.objects.first()
        self.assertIsNotNone(log)
        payload = log.payload_json

        self.assertGreater(Conversacion.objects.filter(id__in=payload.get("conversations", [])).count(), 0)
        self.assertGreater(Mensaje.objects.filter(id__in=payload.get("messages", [])).count(), 0)
        self.assertGreater(Notification.objects.filter(id__in=payload.get("notifications", [])).count(), 0)
        self.assertGreater(
            Notification.objects.filter(dedupe_key__in=payload.get("chat_notification_keys", [])).count(),
            0,
        )

        call_command(
            "seed_demo_comms",
            empresa=self.empresa.id,
            reset=True,
            stdout=out,
        )

        self.assertEqual(
            Conversacion.objects.filter(id__in=payload.get("conversations", [])).count(),
            0,
        )
        self.assertEqual(
            Mensaje.objects.filter(id__in=payload.get("messages", [])).count(),
            0,
        )
        self.assertEqual(
            Notification.objects.filter(id__in=payload.get("notifications", [])).count(),
            0,
        )
        self.assertEqual(
            Notification.objects.filter(dedupe_key__in=payload.get("chat_notification_keys", [])).count(),
            0,
        )
        self.assertEqual(DemoSeedLog.objects.count(), 0)
