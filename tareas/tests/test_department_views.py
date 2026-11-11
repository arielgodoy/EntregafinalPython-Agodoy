"""Contract tests for the department-master VICMEAS surface."""

from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import URLPattern, reverse
from django.urls.converters import (
    IntConverter,
    PathConverter,
    SlugConverter,
    StringConverter,
    UUIDConverter,
)

from access_control.models import (
    Empresa,
    PerfilAcceso,
    Permiso,
    UsuarioPerfilEmpresa,
    Vista,
)
from access_control.services.permissions import ICMEAS_FIELDS
from organizacion.models import (
    Departamento,
    MembresiaDepartamental,
    OrganizationalSource,
)
from organizacion.services.memberships import (
    MembershipCommand,
    MembershipOperation,
    change_membership,
)
from tareas.urls import urlpatterns
from tareas.services.master_catalog_common import MutationResult
from tareas.services.department_catalog import DepartmentRecord


User = get_user_model()
MASTER_VIEW_NAME = "Tareas - Maestro de departamentos"
MASTER_ACTIONS = ("ingresar", "crear", "modificar", "eliminar")
MUTATION_ACTIONS = ("crear", "modificar", "eliminar")


def _master_view_bindings():
    for pattern in urlpatterns:
        if not isinstance(pattern, URLPattern):
            continue
        callback = pattern.callback
        view = getattr(callback, "view_class", callback)
        if getattr(view, "vista_nombre", None) == MASTER_VIEW_NAME:
            yield pattern, view


class DepartmentViewContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(
            codigo="91",
            descripcion="Empresa de contrato T180",
        )
        cls.otra_empresa = Empresa.objects.create(
            codigo="92",
            descripcion="Empresa ajena T180",
        )
        cls.departamento = Departamento.objects.create(
            empresa=cls.empresa,
            codigo="T180",
            nombre="Departamento de contrato",
            source=OrganizationalSource.LOCAL,
        )
        cls.vista = Vista.objects.create(nombre=MASTER_VIEW_NAME)

        cls.usuario_solo_ver = User.objects.create_user(
            username="t180-solo-ver",
            password=None,
        )
        cls.usuario_sin_permiso = User.objects.create_user(
            username="t180-sin-permiso",
            password=None,
        )
        cls.jefe = User.objects.create_user(
            username="t180-jefe",
            password=None,
        )
        cls.usuario_supervisor_icmeas = User.objects.create_user(
            username="t180-supervisor-icmeas",
            password=None,
        )
        cls.usuario_otra_empresa = User.objects.create_user(
            username="t180-otra-empresa",
            password=None,
        )
        cls.administrador_inicial = User.objects.create_user(
            username="t180-admin-inicial",
            password=None,
        )
        cls.usuario_destino = User.objects.create_user(
            username="t180-destino",
            password=None,
        )

        for user in (
            cls.usuario_solo_ver,
            cls.usuario_sin_permiso,
            cls.jefe,
            cls.usuario_supervisor_icmeas,
            cls.usuario_otra_empresa,
            cls.administrador_inicial,
            cls.usuario_destino,
        ):
            cls._grant_company_access(user, cls.empresa)
        cls._grant_company_access(cls.usuario_otra_empresa, cls.otra_empresa)

        cls._grant_permission(cls.usuario_solo_ver, cls.empresa, ver=True)
        cls._grant_permission(cls.jefe, cls.empresa, ver=True)
        cls._grant_permission(
            cls.usuario_supervisor_icmeas,
            cls.empresa,
            supervisor=True,
        )
        cls._grant_permission(
            cls.usuario_otra_empresa,
            cls.otra_empresa,
            crear=True,
        )
        cls._grant_permission(
            cls.administrador_inicial,
            cls.empresa,
            crear=True,
        )

        MembresiaDepartamental.objects.create(
            empresa=cls.empresa,
            departamento=cls.departamento,
            usuario=cls.jefe,
            rol=MembresiaDepartamental.Rol.JEFE,
            estado=MembresiaDepartamental.Estado.ACTIVA,
        )

    @classmethod
    def _grant_company_access(cls, user, empresa):
        profile = PerfilAcceso.objects.create(
            nombre=f"T180 {user.username} {empresa.codigo}",
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=user,
            empresa=empresa,
            perfil=profile,
            asignado_por=user,
        )

    @classmethod
    def _grant_permission(cls, user, empresa, **flags):
        values = {field: False for field in ("ver", *ICMEAS_FIELDS)}
        values.update(flags)
        return Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=cls.vista,
            **values,
        )

    def _bindings_for_action(self, action):
        return [
            (pattern, view)
            for pattern, view in _master_view_bindings()
            if getattr(view, "permiso_requerido", None) == action
        ]

    def _required_binding(self, action):
        bindings = self._bindings_for_action(action)
        self.assertTrue(
            bindings,
            f"T181 must expose a master route protected by {action!r}.",
        )
        return bindings[0]

    def _url_for_pattern(self, pattern):
        self.assertIsNotNone(pattern.name, "Master routes must be reversible.")
        values = {}
        for name, converter in pattern.pattern.converters.items():
            if isinstance(converter, IntConverter):
                values[name] = self.departamento.pk
            elif isinstance(converter, UUIDConverter):
                values[name] = uuid4()
            elif isinstance(
                converter,
                (PathConverter, SlugConverter, StringConverter),
            ):
                values[name] = "t180"
            else:
                self.fail(
                    f"Add a safe test value for URL converter {type(converter).__name__}."
                )
        return reverse(f"tareas:{pattern.name}", kwargs=values)

    def _login_in_company(self, user, empresa):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = empresa.pk
        session.save()

    def test_master_uses_one_approved_vicmeas_identity_and_expected_actions(self):
        bindings = list(_master_view_bindings())
        self.assertTrue(
            bindings,
            "T181 must add real department-master routes before this contract passes.",
        )

        self.assertEqual(
            {getattr(view, "vista_nombre", None) for _, view in bindings},
            {MASTER_VIEW_NAME},
        )
        self.assertEqual(
            {
                getattr(view, "permiso_requerido", None)
                for _, view in bindings
            },
            set(MASTER_ACTIONS),
        )

    def test_contract_actions_are_existing_icmeas_flags(self):
        self.assertTrue(set(MASTER_ACTIONS).issubset(ICMEAS_FIELDS))

    def test_missing_capability_returns_official_403(self):
        self._login_in_company(self.usuario_solo_ver, self.empresa)
        for action in MASTER_ACTIONS:
            with self.subTest(action=action):
                pattern, _ = self._required_binding(action)
                response = self.client.get(self._url_for_pattern(pattern))
                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(
                    response,
                    "access_control/403_forbidden.html",
                )

    def test_organizational_jefe_without_permission_is_denied(self):
        permiso = Permiso.objects.get(
            usuario=self.jefe,
            empresa=self.empresa,
            vista=self.vista,
        )
        self.assertFalse(permiso.supervisor)
        self.assertFalse(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertFalse(permiso.eliminar)

        self._login_in_company(self.jefe, self.empresa)
        for action in MUTATION_ACTIONS:
            with self.subTest(action=action):
                pattern, _ = self._required_binding(action)
                response = self.client.get(self._url_for_pattern(pattern))
                self.assertEqual(response.status_code, 403)

    def test_icmeas_supervisor_flag_keeps_its_official_override(self):
        self._login_in_company(self.usuario_supervisor_icmeas, self.empresa)
        for action in MASTER_ACTIONS:
            with self.subTest(action=action):
                pattern, _ = self._required_binding(action)
                response = self.client.get(self._url_for_pattern(pattern))
                self.assertNotEqual(response.status_code, 403)

    def test_authorized_admin_can_create_first_membership_without_own_membership(self):
        self.assertFalse(
            MembresiaDepartamental.objects.filter(
                empresa=self.empresa,
                usuario=self.administrador_inicial,
            ).exists()
        )
        command = MembershipCommand(
            company_id=self.empresa.pk,
            actor_id=self.administrador_inicial.pk,
            user_id=self.usuario_destino.pk,
            department_id=self.departamento.pk,
            operation_id=uuid4(),
            action=MembershipOperation.CREATE,
            reason="Alta inicial autorizada",
            target_role=MembresiaDepartamental.Rol.STAFF,
            expected_membership_version=None,
            expected_organization_revision=None,
        )

        result = change_membership(command)

        self.assertEqual(result.user_id, self.usuario_destino.pk)
        self.assertTrue(
            MembresiaDepartamental.objects.filter(
                empresa=self.empresa,
                departamento=self.departamento,
                usuario=self.usuario_destino,
            ).exists()
        )
        self.assertFalse(
            MembresiaDepartamental.objects.filter(
                empresa=self.empresa,
                usuario=self.administrador_inicial,
            ).exists()
        )

    def test_initial_admin_without_membership_is_not_rejected_by_master_view(self):
        pattern, _ = self._required_binding("crear")
        self._login_in_company(self.administrador_inicial, self.empresa)

        response = self.client.get(self._url_for_pattern(pattern))

        self.assertNotEqual(response.status_code, 403)
        self.assertFalse(
            MembresiaDepartamental.objects.filter(
                empresa=self.empresa,
                usuario=self.administrador_inicial,
            ).exists()
        )

    def test_permission_from_other_company_does_not_authorize_active_company(self):
        pattern, _ = self._required_binding("crear")
        self._login_in_company(self.usuario_otra_empresa, self.empresa)

        response = self.client.get(self._url_for_pattern(pattern))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.usuario_otra_empresa,
                empresa=self.empresa,
                vista=self.vista,
            ).exists()
        )

    def test_denial_does_not_create_permission_or_mutate_organization(self):
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.usuario_sin_permiso,
                empresa=self.empresa,
                vista=self.vista,
            ).exists()
        )
        initial_departments = Departamento.objects.count()
        initial_memberships = MembresiaDepartamental.objects.count()
        self._login_in_company(self.usuario_sin_permiso, self.empresa)

        for action in MASTER_ACTIONS:
            with self.subTest(action=action):
                pattern, _ = self._required_binding(action)
                response = self.client.get(self._url_for_pattern(pattern))
                self.assertEqual(response.status_code, 403)
                self.assertFalse(
                    Permiso.objects.filter(
                        usuario=self.usuario_sin_permiso,
                        empresa=self.empresa,
                        vista=self.vista,
                    ).exists()
                )
                self.assertEqual(Departamento.objects.count(), initial_departments)
                self.assertEqual(
                    MembresiaDepartamental.objects.count(),
                    initial_memberships,
                )

    def test_create_endpoint_uses_session_company_and_returns_controlled_json(self):
        self._login_in_company(self.administrador_inicial, self.empresa)
        operation_id = uuid4()
        with patch(
            "tareas.views.create_department",
            return_value=MutationResult(
                71001,
                str(operation_id),
                audit_status="CONFIRMED",
            ),
        ) as create:
            response = self.client.post(
                reverse("tareas:departamentos_maestro_crear"),
                {
                    "codigo": "HTTP-1",
                    "nombre": "Departamento HTTP",
                    "motivo": "Alta autorizada",
                    "operation_id": str(operation_id),
                    "empresa_id": self.otra_empresa.pk,
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["id"], 71001)
        create.assert_called_once()
        context = create.call_args.args[0]
        self.assertEqual(context.empresa_id, self.empresa.pk)

    def test_master_template_renders_target_catalog_records(self):
        self._login_in_company(self.usuario_supervisor_icmeas, self.empresa)
        department = DepartmentRecord(
            id=71002,
            empresa_id=self.empresa.pk,
            codigo="D-71002",
            nombre="Departamento de prueba",
            activo=True,
            source="LOCAL",
            created_at=None,
            updated_at=None,
        )
        with patch(
            "tareas.views.list_departments",
            return_value=(department,),
        ):
            response = self.client.get(reverse("tareas:departamentos_maestro"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Departamento de prueba")
        self.assertContains(response, "tareas.master_catalog.department.edit")

    def test_create_endpoint_is_post_only(self):
        self._login_in_company(self.administrador_inicial, self.empresa)
        with patch("tareas.views.create_department") as create:
            response = self.client.get(
                reverse("tareas:departamentos_maestro_crear")
            )

        self.assertEqual(response.status_code, 405)
        create.assert_not_called()

    def test_create_endpoint_enforces_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrador_inicial)
        session = client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

        with patch("tareas.views.create_department") as create:
            response = client.post(
                reverse("tareas:departamentos_maestro_crear"),
                {
                    "codigo": "CSRF-1",
                    "nombre": "Departamento CSRF",
                    "motivo": "Alta autorizada",
                    "operation_id": str(uuid4()),
                },
            )

        self.assertEqual(response.status_code, 403)
        create.assert_not_called()

    def test_update_endpoint_uses_modificar_permission_and_name_only(self):
        permiso = Permiso.objects.get(
            usuario=self.administrador_inicial,
            empresa=self.empresa,
            vista=self.vista,
        )
        permiso.modificar = True
        permiso.save(update_fields=["modificar"])
        self._login_in_company(self.administrador_inicial, self.empresa)
        operation_id = uuid4()

        with patch(
            "tareas.views.update_department_name",
            return_value=MutationResult(
                self.departamento.pk,
                str(operation_id),
                audit_status="CONFIRMED",
            ),
        ) as update:
            response = self.client.post(
                reverse(
                    "tareas:departamentos_maestro_editar",
                    kwargs={"department_id": self.departamento.pk},
                ),
                {
                    "nombre": "Nombre actualizado",
                    "motivo": "Corrección autorizada",
                    "operation_id": str(operation_id),
                    "codigo": "MANIPULADO",
                    "empresa_id": self.otra_empresa.pk,
                    "source": "ERP",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["id"], self.departamento.pk)
        update.assert_called_once()
        context = update.call_args.args[0]
        self.assertEqual(context.empresa_id, self.empresa.pk)
        self.assertEqual(update.call_args.args[2], "Nombre actualizado")

    def test_delete_endpoint_uses_eliminar_permission_and_returns_controlled_json(self):
        permiso = Permiso.objects.get(
            usuario=self.administrador_inicial,
            empresa=self.empresa,
            vista=self.vista,
        )
        permiso.eliminar = True
        permiso.save(update_fields=["eliminar"])
        self._login_in_company(self.administrador_inicial, self.empresa)
        operation_id = uuid4()

        with patch(
            "tareas.views.delete_department",
            return_value=MutationResult(
                self.departamento.pk,
                str(operation_id),
                audit_status="CONFIRMED",
            ),
        ) as delete:
            response = self.client.post(
                reverse(
                    "tareas:departamentos_maestro_eliminar",
                    kwargs={"department_id": self.departamento.pk},
                ),
                {
                    "motivo": "Eliminación de prueba",
                    "operation_id": str(operation_id),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[0].empresa_id, self.empresa.pk)

    def test_delete_endpoint_is_post_only(self):
        permiso = Permiso.objects.get(
            usuario=self.administrador_inicial,
            empresa=self.empresa,
            vista=self.vista,
        )
        permiso.eliminar = True
        permiso.save(update_fields=["eliminar"])
        self._login_in_company(self.administrador_inicial, self.empresa)

        with patch("tareas.views.delete_department") as delete:
            response = self.client.get(
                reverse(
                    "tareas:departamentos_maestro_eliminar",
                    kwargs={"department_id": self.departamento.pk},
                )
            )

        self.assertEqual(response.status_code, 405)
        delete.assert_not_called()
