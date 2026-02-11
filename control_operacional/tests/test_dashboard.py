from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from control_de_proyectos.models import ClienteEmpresa, Proyecto
from control_operacional.models import RegistroOperacional


class ControlOperacionalDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass1234")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(nombre="Control Operacional Dashboard")

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

    def test_registro_operacional_str(self):
        registro = RegistroOperacional.objects.create(empresa=self.empresa, titulo="Registro Uno")
        self.assertEqual(str(registro), "Registro Uno")

    def test_dashboard_redirects_without_empresa(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("access_control:seleccionar_empresa"))

    def test_dashboard_ok_with_permiso(self):
        self._login_with_empresa()
        self._grant_ingresar()
        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="control_operacional.dashboard.title"')

    def test_dashboard_kpis_scoped_por_empresa(self):
        empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        cliente_a = ClienteEmpresa.objects.create(nombre="Cliente A", rut="12.345.678-5")
        cliente_b = ClienteEmpresa.objects.create(nombre="Cliente B", rut="76.543.210-3")

        self._login_with_empresa()
        self._grant_ingresar()

        Proyecto.objects.create(
            nombre="Proyecto A1",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="EN_EJECUCION",
            activo=True,
        )
        Proyecto.objects.create(
            nombre="Proyecto A2",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="EN_COTIZACION",
            activo=True,
        )
        Proyecto.objects.create(
            nombre="Proyecto A3",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="EN_COTIZACION",
            activo=True,
        )
        Proyecto.objects.create(
            nombre="Proyecto A4",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="TERMINADO",
            activo=True,
        )
        Proyecto.objects.create(
            nombre="Proyecto A5",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="EN_EJECUCION",
            activo=False,
        )

        for index in range(5):
            Proyecto.objects.create(
                nombre=f"Proyecto B{index + 1}",
                empresa_interna=empresa_b,
                cliente=cliente_b,
                tipo_texto="Operacional",
                estado="EN_EJECUCION",
                activo=True,
            )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)

        kpis = response.context.get("kpis")
        self.assertIsNotNone(kpis)
        self.assertEqual(kpis.get("total_activos"), 4)
        self.assertEqual(kpis.get("en_ejecucion"), 1)
        self.assertEqual(kpis.get("en_cotizacion"), 2)
        self.assertEqual(kpis.get("terminados"), 1)

    def test_chart_proyectos_por_estado_scoped_y_buckets(self):
        empresa_b = Empresa.objects.create(codigo="03", descripcion="Empresa 03")
        cliente_a = ClienteEmpresa.objects.create(nombre="Cliente Chart A", rut="11.111.111-1")
        cliente_b = ClienteEmpresa.objects.create(nombre="Cliente Chart B", rut="22.222.222-2")

        self._login_with_empresa()
        self._grant_ingresar()

        for index in range(2):
            Proyecto.objects.create(
                nombre=f"Proyecto Ejecucion {index + 1}",
                empresa_interna=self.empresa,
                cliente=cliente_a,
                tipo_texto="Operacional",
                estado="EN_EJECUCION",
                activo=True,
            )

        Proyecto.objects.create(
            nombre="Proyecto Cotizacion",
            empresa_interna=self.empresa,
            cliente=cliente_a,
            tipo_texto="Operacional",
            estado="EN_COTIZACION",
            activo=True,
        )

        for index in range(3):
            Proyecto.objects.create(
                nombre=f"Proyecto Terminado {index + 1}",
                empresa_interna=self.empresa,
                cliente=cliente_a,
                tipo_texto="Operacional",
                estado="TERMINADO",
                activo=True,
            )

        for index in range(4):
            Proyecto.objects.create(
                nombre=f"Proyecto Otro {index + 1}",
                empresa_interna=self.empresa,
                cliente=cliente_a,
                tipo_texto="Operacional",
                estado="FUTURO_ESTUDIO",
                activo=True,
            )

        for index in range(3):
            Proyecto.objects.create(
                nombre=f"Proyecto B{index + 1}",
                empresa_interna=empresa_b,
                cliente=cliente_b,
                tipo_texto="Operacional",
                estado="EN_EJECUCION",
                activo=True,
            )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)

        chart_data = response.context.get("chart_proyectos_por_estado")
        self.assertIsNotNone(chart_data)
        self.assertEqual(chart_data.get("series"), [2, 1, 3, 4])
        self.assertEqual(
            chart_data.get("labels_keys"),
            [
                "control_operacional.estado.en_ejecucion",
                "control_operacional.estado.en_cotizacion",
                "control_operacional.estado.terminado",
                "control_operacional.estado.otros",
            ],
        )
