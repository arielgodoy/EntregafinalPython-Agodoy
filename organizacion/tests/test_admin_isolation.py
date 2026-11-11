from types import SimpleNamespace
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.db import models
from django.test import RequestFactory, TestCase
from django.urls import reverse

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from access_control.services.empresa_activa import set_empresa_activa_en_sesion
from organizacion.models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    MembresiaDepartamental,
)


User = get_user_model()
ORGANIZATION_MODELS = (
    MembresiaDepartamental,
    EventoMembresia,
    ControlOrganizacionEmpresa,
)


class OrganizationAdminIsolationTests(TestCase):
    def setUp(self):
        self.empresa_activa = Empresa.objects.create(codigo="71", descripcion="Empresa activa")
        self.empresa_ajena = Empresa.objects.create(codigo="72", descripcion="Empresa ajena")
        self.staff = User.objects.create_user(
            username="admin-org-scoped",
            password="test-password",
            is_staff=True,
        )
        self.usuario_ajeno = User.objects.create_user(
            username="usuario-empresa-ajena",
            password="test-password",
        )
        self._assign_company(self.staff, self.empresa_activa)
        self._assign_company(self.usuario_ajeno, self.empresa_ajena)
        self._grant_admin_view_permissions(self.staff)

        self.departamento_activo = Departamento.objects.create(
            empresa=self.empresa_activa,
            codigo="DA",
            nombre="Departamento activo",
        )
        self.departamento_ajeno = Departamento.objects.create(
            empresa=self.empresa_ajena,
            codigo="DB",
            nombre="Departamento ajeno confidencial",
        )
        self.membresia_activa = self._create_membership(
            self.empresa_activa,
            self.departamento_activo,
            self.staff,
            rol="STAFF",
        )
        self.membresia_ajena = self._create_membership(
            self.empresa_ajena,
            self.departamento_ajeno,
            self.usuario_ajeno,
            rol="JEFE",
        )
        self.evento_activo = self._create_event(self.membresia_activa, self.staff)
        self.evento_ajeno = self._create_event(self.membresia_ajena, self.usuario_ajeno)
        self.control_activo = ControlOrganizacionEmpresa.objects.create(
            empresa=self.empresa_activa
        )
        self.control_ajeno = ControlOrganizacionEmpresa.objects.create(
            empresa=self.empresa_ajena
        )

    def _assign_company(self, user, empresa):
        perfil = PerfilAcceso.objects.create(nombre=f"Perfil {empresa.codigo} {user.pk}")
        UsuarioPerfilEmpresa.objects.create(
            usuario=user,
            empresa=empresa,
            perfil=perfil,
            asignado_por=user,
        )

    def _grant_admin_view_permissions(self, user):
        for model in ORGANIZATION_MODELS:
            permission = Permission.objects.get(
                content_type__app_label="organizacion",
                codename=f"view_{model._meta.model_name}",
            )
            user.user_permissions.add(permission)

    def _create_membership(self, empresa, departamento, usuario, *, rol):
        return MembresiaDepartamental.objects.create(
            empresa=empresa,
            departamento=departamento,
            usuario=usuario,
            rol=rol,
            estado="ACTIVA",
        )

    def _create_event(self, membership, actor):
        return EventoMembresia.objects.create(
            membresia=membership,
            empresa_id=membership.empresa_id,
            usuario_afectado_id=membership.usuario_id,
            departamento_id=membership.departamento_id,
            autor=actor,
            operacion_id=uuid4(),
            tipo="ALTA",
            motivo="Registro inicial",
            rol_despues=membership.rol,
            estado_despues=membership.estado,
            version_despues=membership.version,
        )

    def _request(self, user=None, empresa=None, *, get_query=""):
        request = RequestFactory().get(f"/admin/{get_query}")
        request.user = user or self.staff
        request.session = SessionStore()
        if empresa is not None:
            set_empresa_activa_en_sesion(request, empresa)
        return request

    def _set_client_empresa(self, empresa):
        session = self.client.session
        set_empresa_activa_en_sesion(SimpleNamespace(session=session), empresa)
        session.save()

    def _changelist_url(self, model):
        return reverse(f"admin:organizacion_{model._meta.model_name}_changelist")

    def _change_url(self, obj):
        return reverse(
            f"admin:organizacion_{obj._meta.model_name}_change",
            args=(obj.pk,),
        )

    def test_all_three_models_are_registered_with_view_only_permissions(self):
        request = self._request(empresa=self.empresa_activa)
        for model in ORGANIZATION_MODELS:
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                self.assertIsNotNone(model_admin)
                self.assertTrue(model_admin.has_view_permission(request))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))
                self.assertIsNone(model_admin.actions)
                self.assertEqual(model_admin.get_inline_instances(request), [])
                self.assertEqual(
                    set(model_admin.get_fields(request)),
                    set(model_admin.get_readonly_fields(request)),
                )

    def test_queryset_for_every_model_is_scoped_to_authorized_active_company(self):
        request = self._request(empresa=self.empresa_activa, get_query="?empresa=72")
        expected = {
            MembresiaDepartamental: self.membresia_activa.pk,
            EventoMembresia: self.evento_activo.pk,
            ControlOrganizacionEmpresa: self.control_activo.pk,
        }
        for model, active_pk in expected.items():
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                rows = model_admin.get_queryset(request)
                self.assertEqual(list(rows.values_list("pk", flat=True)), [active_pk])
                self.assertNotIn(
                    model.objects.get(
                        pk={
                            MembresiaDepartamental: self.membresia_ajena.pk,
                            EventoMembresia: self.evento_ajeno.pk,
                            ControlOrganizacionEmpresa: self.control_ajeno.pk,
                        }[model]
                    ),
                    rows,
                )

    def test_active_company_is_set_by_official_selector_and_admin_pages_are_scoped(self):
        self.client.force_login(self.staff)
        self._set_client_empresa(self.empresa_activa)

        for model in ORGANIZATION_MODELS:
            with self.subTest(model=model._meta.label):
                response = self.client.get(self._changelist_url(model))
                self.assertEqual(response.status_code, 200)
                content = response.content.decode()
                self.assertIn("Empresa activa", content)
                self.assertNotIn("Empresa ajena", content)
                self.assertNotIn("Departamento ajeno confidencial", content)
                self.assertNotIn("usuario-empresa-ajena", content)

    def test_related_filters_do_not_enumerate_other_company_values(self):
        request = self._request(empresa=self.empresa_activa)
        forbidden_related_filters = {"empresa", "departamento", "usuario", "membresia"}
        for model in ORGANIZATION_MODELS:
            with self.subTest(model=model._meta.label):
                list_filter = set(admin.site._registry[model].get_list_filter(request))
                self.assertTrue(forbidden_related_filters.isdisjoint(list_filter))

        self.client.force_login(self.staff)
        self._set_client_empresa(self.empresa_activa)
        response = self.client.get(
            f"{self._changelist_url(MembresiaDepartamental)}?q=usuario-empresa-ajena"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 0)
        self.assertEqual(list(response.context["cl"].result_list), [])

    def test_individual_objects_from_another_company_are_not_retrievable(self):
        request = self._request(empresa=self.empresa_activa)
        foreign_objects = (
            self.membresia_ajena,
            self.evento_ajeno,
            self.control_ajeno,
        )
        self.client.force_login(self.staff)
        self._set_client_empresa(self.empresa_activa)

        for obj in foreign_objects:
            with self.subTest(model=obj._meta.label):
                model_admin = admin.site._registry[type(obj)]
                self.assertFalse(model_admin.has_view_permission(request, obj))
                self.assertIsNone(model_admin.get_object(request, str(obj.pk)))
                response = self.client.get(self._change_url(obj))
                self.assertNotEqual(response.status_code, 200)
                self.assertNotIn("Departamento ajeno confidencial", response.content.decode())

    def test_inconsistent_cross_company_references_are_not_displayed(self):
        inconsistent_membership = MembresiaDepartamental(
            empresa=self.empresa_activa,
            departamento=self.departamento_ajeno,
            usuario=self.usuario_ajeno,
            rol="STAFF",
        )
        models.Model.save(inconsistent_membership)
        inconsistent_event = EventoMembresia(
            membresia=inconsistent_membership,
            empresa=self.empresa_activa,
            departamento=self.departamento_ajeno,
            usuario_afectado=self.usuario_ajeno,
            autor=self.staff,
            operacion_id=uuid4(),
            tipo="ALTA",
            motivo="Evento con referencias inconsistentes",
            rol_despues="STAFF",
            estado_despues="ACTIVA",
            version_despues=1,
        )
        models.Model.save(inconsistent_event)

        request = self._request(empresa=self.empresa_activa)
        for obj in (inconsistent_membership, inconsistent_event):
            with self.subTest(model=obj._meta.label):
                queryset = admin.site._registry[type(obj)].get_queryset(request)
                self.assertFalse(queryset.filter(pk=obj.pk).exists())

    def test_missing_invalid_or_unauthorized_company_context_denies_queries(self):
        model_admin = admin.site._registry[MembresiaDepartamental]
        for raw_company_id in (None, "", "invalid", "71.5", True, 0, 999):
            with self.subTest(raw_company_id=raw_company_id):
                request = self._request()
                if raw_company_id is not None:
                    request.session["empresa_id"] = raw_company_id
                self.assertFalse(model_admin.has_view_permission(request))
                self.assertFalse(model_admin.get_queryset(request).exists())

        outsider = User.objects.create_user(
            username="staff-without-company-access",
            password="test-password",
            is_staff=True,
        )
        self._grant_admin_view_permissions(outsider)
        request = self._request(outsider, self.empresa_activa)
        self.assertFalse(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.get_queryset(request).exists())
        self.client.force_login(outsider)
        self._set_client_empresa(self.empresa_activa)
        self.assertEqual(self.client.get(self._changelist_url(MembresiaDepartamental)).status_code, 403)

        self.client.force_login(self.staff)
        for invalid_company_id in ("invalid", "71.5", True, 0, 999):
            with self.subTest(http_company_id=invalid_company_id):
                session = self.client.session
                session["empresa_id"] = invalid_company_id
                session.save()
                self.assertEqual(
                    self.client.get(self._changelist_url(MembresiaDepartamental)).status_code,
                    403,
                )
        session = self.client.session
        session.pop("empresa_id", None)
        session.save()
        self.assertEqual(self.client.get(self._changelist_url(MembresiaDepartamental)).status_code, 403)

    def test_department_role_alone_does_not_authorize_company_admin_read(self):
        leader = User.objects.create_user(
            username="staff-department-leader",
            password="test-password",
            is_staff=True,
        )
        self._grant_admin_view_permissions(leader)
        self._create_membership(
            self.empresa_activa,
            self.departamento_activo,
            leader,
            rol="JEFE",
        )
        request = self._request(leader, self.empresa_activa)

        model_admin = admin.site._registry[MembresiaDepartamental]
        self.assertFalse(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.get_queryset(request).exists())

    def test_missing_django_admin_view_permission_denies_authorized_company_user(self):
        profile_only_staff = User.objects.create_user(
            username="staff-with-company-but-no-admin-view",
            password="test-password",
            is_staff=True,
        )
        self._assign_company(profile_only_staff, self.empresa_activa)
        request = self._request(profile_only_staff, self.empresa_activa)

        model_admin = admin.site._registry[MembresiaDepartamental]
        self.assertFalse(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.get_queryset(request).exists())
        self.client.force_login(profile_only_staff)
        self._set_client_empresa(self.empresa_activa)
        self.assertEqual(self.client.get(self._changelist_url(MembresiaDepartamental)).status_code, 403)

    def test_admin_get_pages_work_but_all_mutating_posts_are_denied(self):
        self.client.force_login(self.staff)
        self._set_client_empresa(self.empresa_activa)

        own_objects = (
            self.membresia_activa,
            self.evento_activo,
            self.control_activo,
        )
        for obj in own_objects:
            with self.subTest(model=obj._meta.label):
                model_admin = admin.site._registry[type(obj)]
                before_count = type(obj).objects.count()
                self.assertEqual(self.client.get(self._changelist_url(type(obj))).status_code, 200)
                self.assertEqual(self.client.get(self._change_url(obj)).status_code, 200)
                self.assertEqual(
                    self.client.post(
                        reverse(f"admin:organizacion_{obj._meta.model_name}_add"),
                        {"_save": "Guardar"},
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(self._change_url(obj), {"_save": "Guardar"}).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        reverse(
                            f"admin:organizacion_{obj._meta.model_name}_delete",
                            args=(obj.pk,),
                        ),
                        {"post": "yes"},
                    ).status_code,
                    403,
                )
                obj.refresh_from_db()
                self.assertEqual(type(obj).objects.count(), before_count)
                self.assertFalse(model_admin.has_add_permission(self._request(empresa=self.empresa_activa)))
                self.assertFalse(
                    model_admin.has_change_permission(self._request(empresa=self.empresa_activa), obj)
                )
                self.assertFalse(
                    model_admin.has_delete_permission(self._request(empresa=self.empresa_activa), obj)
                )
