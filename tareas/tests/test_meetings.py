from datetime import date, datetime, time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from organizacion.models import Departamento, Local, OrganizationalSource
from tareas.forms import ReunionRevisionForm
from tareas.models import ReunionRevision, Tarea, TareaConnectionRole
from tareas.services.meetings import (
    _validate_meeting_scope,
    add_meeting_participant,
    add_task_to_meeting,
    convene_meeting,
    create_meeting,
    mark_meeting_completed,
    update_meeting,
)
from tareas.services.meeting_storage import (
    DjangoMeetingStorage,
    MySQLMeetingStorage,
)


class MeetingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={"source_type": "DJANGO", "django_alias": "default"},
        )
        cls.empresa = Empresa.objects.create(codigo="M55", descripcion="Empresa reunión")
        cls.otra_empresa = Empresa.objects.create(
            codigo="M56",
            descripcion="Otra Empresa",
        )
        cls.user = User.objects.create_user(username="meeting_creator", email="creator@example.test")
        cls.participant = User.objects.create_user(username="meeting_participant", email="participant@example.test")
        vista = Vista.objects.create(nombre="Tareas")
        vista_reuniones = Vista.objects.create(nombre="Tareas - Reuniones")
        for user in (cls.user, cls.participant):
            Permiso.objects.create(usuario=user, empresa=cls.empresa, vista=vista, ingresar=True, crear=True, modificar=True)
            Permiso.objects.create(
                usuario=user,
                empresa=cls.empresa,
                vista=vista_reuniones,
                ingresar=True,
                crear=True,
                modificar=True,
            )
        cls.local = Local.objects.create(
            empresa=cls.empresa, codigo="LOC-M55", nombre="Local reunión", source=OrganizationalSource.LOCAL
        )
        cls.department = Departamento.objects.create(
            empresa=cls.empresa, codigo="DEP-M55", nombre="Departamento reunión", source=OrganizationalSource.LOCAL
        )
        cls.local_inactivo = Local.objects.create(
            empresa=cls.empresa,
            codigo="LOC-M55-X",
            nombre="Local inactivo",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )
        cls.department_inactivo = Departamento.objects.create(
            empresa=cls.empresa,
            codigo="DEP-M55-X",
            nombre="Departamento inactivo",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )
        cls.local_otra_empresa = Local.objects.create(
            empresa=cls.otra_empresa,
            codigo="LOC-M56",
            nombre="Local otra empresa",
            source=OrganizationalSource.LOCAL,
        )
        cls.department_otra_empresa = Departamento.objects.create(
            empresa=cls.otra_empresa,
            codigo="DEP-M56",
            nombre="Departamento otra empresa",
            source=OrganizationalSource.LOCAL,
        )

    def meeting(self, **changes):
        values = {
            "empresa": self.empresa,
            "creada_por": self.user,
            "titulo": "Revisión operativa",
            "descripcion": "Objetivo",
            "fecha_hora_programada": datetime.combine(date(2026, 9, 20), time(10, 0)),
            "modalidad": ReunionRevision.Modalidad.ZOOM,
            "lugar_o_enlace": "https://zoom.example.test/reunion",
            "tipo_ambito": ReunionRevision.TipoAmbito.LOCAL,
            "local": self.local,
        }
        values.update(changes)
        return create_meeting(**values)

    def task(self, **changes):
        values = {
            "titulo": "Tarea revisable",
            "empresa": self.empresa,
            "creada_por": self.user,
            "responsable": self.user,
            "fecha_tope": date(2026, 9, 30),
            "tipo_ambito": Tarea.Ambito.LOCAL,
            "local": self.local,
        }
        values.update(changes)
        task = Tarea.objects.create(**values)
        task.publicar(self.user)
        return task

    def test_create_meeting_creates_published_planned_task(self):
        meeting = self.meeting()
        self.assertEqual(meeting.estado, ReunionRevision.Estado.PLANIFICADA)
        self.assertEqual(meeting.tarea_planificada.estado, Tarea.Estado.ACTIVA)
        self.assertEqual(meeting.tarea_planificada.local_id, self.local.pk)

    def test_create_department_meeting_creates_published_planned_task(self):
        meeting = self.meeting(
            tipo_ambito=ReunionRevision.TipoAmbito.DEPARTAMENTO,
            local=None,
            departamento=self.department,
        )

        self.assertEqual(meeting.empresa_id, self.empresa.pk)
        self.assertEqual(
            meeting.tipo_ambito,
            ReunionRevision.TipoAmbito.DEPARTAMENTO,
        )
        self.assertIsNone(meeting.local_id)
        self.assertEqual(meeting.departamento_id, self.department.pk)
        self.assertEqual(meeting.tarea_planificada.empresa_id, self.empresa.pk)
        self.assertEqual(
            meeting.tarea_planificada.tipo_ambito,
            Tarea.Ambito.DEPARTAMENTO,
        )
        self.assertIsNone(meeting.tarea_planificada.local_id)
        self.assertEqual(
            meeting.tarea_planificada.departamento_id,
            self.department.pk,
        )
        self.assertEqual(
            meeting.tarea_planificada.estado,
            Tarea.Estado.ACTIVA,
        )

    def test_create_meeting_requires_both_vicmeas_create_permissions(self):
        meetings_permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista__nombre="Tareas - Reuniones",
        )
        tasks_permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista__nombre="Tareas",
        )

        meetings_permission.crear = False
        meetings_permission.save(update_fields=["crear"])
        with self.assertRaises(PermissionDenied):
            self.meeting()
        meetings_permission.crear = True
        meetings_permission.save(update_fields=["crear"])
        tasks_permission.crear = False
        tasks_permission.save(update_fields=["crear"])
        with self.assertRaises(PermissionDenied):
            self.meeting()

    def test_revision_form_limits_new_options_to_active_company_records(self):
        form = ReunionRevisionForm(empresa=self.empresa)
        self.assertEqual(
            set(form.fields["local"].queryset.values_list("pk", flat=True)),
            {self.local.pk},
        )
        self.assertEqual(
            set(
                form.fields["departamento"].queryset.values_list("pk", flat=True)
            ),
            {self.department.pk},
        )

        unscoped_form = ReunionRevisionForm()
        self.assertFalse(unscoped_form.fields["local"].queryset.exists())
        self.assertFalse(unscoped_form.fields["departamento"].queryset.exists())

    def test_revision_form_validates_scope_against_session_company(self):
        form = ReunionRevisionForm(
            data={
                "titulo": "Reunión válida",
                "descripcion": "",
                "fecha_hora_programada": "2026-10-28T10:00",
                "modalidad": ReunionRevision.Modalidad.ZOOM,
                "lugar_o_enlace": "",
                "tipo_ambito": ReunionRevision.TipoAmbito.LOCAL,
                "local": str(self.local.pk),
                "departamento": "",
            },
            empresa=self.empresa,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.empresa_id, self.empresa.pk)

    def test_revision_form_preserves_only_its_inactive_historical_scope(self):
        meeting = self.meeting()
        self.local.activo = False
        self.local.save(update_fields=["activo"])

        form = ReunionRevisionForm(instance=meeting, empresa=self.empresa)
        local_ids = set(form.fields["local"].queryset.values_list("pk", flat=True))
        department_ids = set(
            form.fields["departamento"].queryset.values_list("pk", flat=True)
        )

        self.assertIn(self.local.pk, local_ids)
        self.assertNotIn(self.local_inactivo.pk, local_ids)
        self.assertNotIn(self.local_otra_empresa.pk, local_ids)
        self.assertEqual(department_ids, {self.department.pk})

    def test_revision_form_rejects_inactive_and_incompatible_posted_scope(self):
        invalid_scopes = (
            (
                ReunionRevision.TipoAmbito.LOCAL,
                self.local_inactivo.pk,
                "",
                "local",
                "tareas.meetings.errors.selection_invalid",
            ),
            (
                ReunionRevision.TipoAmbito.DEPARTAMENTO,
                "",
                self.department_inactivo.pk,
                "departamento",
                "tareas.meetings.errors.selection_invalid",
            ),
            (
                ReunionRevision.TipoAmbito.LOCAL,
                self.local.pk,
                self.department.pk,
                "departamento",
                "tareas.meetings.errors.scope_incompatible",
            ),
            (
                ReunionRevision.TipoAmbito.DEPARTAMENTO,
                self.local.pk,
                self.department.pk,
                "local",
                "tareas.meetings.errors.scope_incompatible",
            ),
        )

        for tipo_ambito, local_id, department_id, error_field, error_key in invalid_scopes:
            with self.subTest(tipo_ambito=tipo_ambito, error_field=error_field):
                form = ReunionRevisionForm(
                    data={
                        "titulo": "Reunión de prueba",
                        "descripcion": "",
                        "fecha_hora_programada": "2026-10-28T10:00",
                        "modalidad": ReunionRevision.Modalidad.ZOOM,
                        "lugar_o_enlace": "",
                        "tipo_ambito": tipo_ambito,
                        "local": local_id,
                        "departamento": department_id,
                    },
                    empresa=self.empresa,
                )

                self.assertFalse(form.is_valid())
                self.assertIn(error_field, form.errors)
                field_errors = form.errors.as_data()[error_field]
                self.assertEqual(len(field_errors), 1)
                self.assertEqual(field_errors[0].message, error_key)

    def test_service_rejects_foreign_and_inactive_scope_records(self):
        before_meetings = ReunionRevision.objects.count()
        before_tasks = Tarea.objects.count()
        invalid_scopes = (
            ({"local": self.local_inactivo}, "tareas.meetings.errors.local_inactive"),
            ({"local": self.local_otra_empresa}, "tareas.meetings.errors.local_company"),
            (
                {
                    "tipo_ambito": ReunionRevision.TipoAmbito.DEPARTAMENTO,
                    "local": None,
                    "departamento": self.department_inactivo,
                },
                "tareas.meetings.errors.department_inactive",
            ),
            (
                {
                    "tipo_ambito": ReunionRevision.TipoAmbito.DEPARTAMENTO,
                    "local": None,
                    "departamento": self.department_otra_empresa,
                },
                "tareas.meetings.errors.department_company",
            ),
        )

        for scope, error_key in invalid_scopes:
            with self.subTest(scope=scope):
                with self.assertRaises(ValidationError) as raised:
                    self.meeting(**scope)
                self.assertEqual(raised.exception.code, error_key)

        self.assertEqual(ReunionRevision.objects.count(), before_meetings)
        self.assertEqual(Tarea.objects.count(), before_tasks)

    def test_scope_validator_reports_missing_company_with_i18n_code(self):
        with self.assertRaises(ValidationError) as raised:
            _validate_meeting_scope(
                None,
                ReunionRevision.TipoAmbito.LOCAL,
                self.local,
                None,
            )

        self.assertEqual(
            raised.exception.code,
            "tareas.meetings.errors.company_invalid",
        )

    def test_mysql_backend_does_not_bypass_inactive_scope_validation(self):
        storage = MySQLMeetingStorage(object(), "meetings_test")
        with patch(
            "tareas.services.meetings.resolve_meeting_storage",
            return_value=storage,
        ), patch(
            "tareas.services.meeting_storage.open_mysql_connection"
        ) as open_connection:
            with self.assertRaises(ValidationError) as raised:
                self.meeting(local=self.local_inactivo)

        self.assertEqual(
            raised.exception.code,
            "tareas.meetings.errors.local_inactive",
        )
        open_connection.assert_not_called()

    def test_update_preserves_original_inactive_scope_but_rejects_replacement(self):
        meeting = self.meeting()
        self.local.activo = False
        self.local.save(update_fields=["activo"])

        updated = update_meeting(meeting, titulo="Título actualizado")
        self.assertEqual(updated.titulo, "Título actualizado")
        self.assertEqual(updated.local_id, self.local.pk)

        with self.assertRaises(ValidationError) as raised:
            update_meeting(updated, local=self.local_inactivo)
        self.assertEqual(
            raised.exception.code,
            "tareas.meetings.errors.historical_reference_invalid",
        )

    def test_scope_xor_is_enforced(self):
        with self.assertRaises(ValidationError) as local_scope_error:
            self.meeting(local=None)
        with self.assertRaises(ValidationError) as mixed_scope_error:
            self.meeting(departamento=self.department)
        self.assertEqual(
            local_scope_error.exception.code,
            "tareas.meetings.errors.scope_incompatible",
        )
        self.assertEqual(
            mixed_scope_error.exception.code,
            "tareas.meetings.errors.scope_incompatible",
        )

    def test_agenda_requires_same_scope(self):
        meeting = self.meeting()
        item = add_task_to_meeting(reunion=meeting, tarea=self.task(), orden=1)
        self.assertEqual(item.reunion_id, meeting.pk)
        with self.assertRaises(ValidationError):
            add_task_to_meeting(
                reunion=meeting,
                tarea=self.task(tipo_ambito=Tarea.Ambito.DEPARTAMENTO, local=None, departamento=self.department),
                orden=2,
            )

    @patch("tareas.services.meetings.send_task_email")
    @patch("tareas.services.meetings.notify_task_event")
    def test_convene_notifies_once_and_records_timestamp(self, notify, email):
        meeting = self.meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participant)
        with self.captureOnCommitCallbacks(execute=True):
            convene_meeting(meeting, actor=self.user)
        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.convocada_at)
        notify.assert_called_once()
        email.assert_called_once()
        with self.assertRaises(ValidationError):
            convene_meeting(meeting)

    @patch("tareas.services.meetings.send_task_email")
    @patch("tareas.services.meetings.notify_task_event")
    def test_convene_defers_notifications_until_commit(self, notify, email):
        meeting = self.meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participant)

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with transaction.atomic():
                convene_meeting(meeting, actor=self.user)
                notify.assert_not_called()
                email.assert_not_called()

        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.convocada_at)
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        notify.assert_called_once()
        email.assert_called_once()

    @patch("tareas.services.meetings.send_task_email")
    @patch("tareas.services.meetings.notify_task_event")
    @patch.object(DjangoMeetingStorage, "mark_convened", side_effect=RuntimeError("persist meeting"))
    def test_convene_persistence_failure_does_not_notify(
        self, mark_convened, notify, email
    ):
        meeting = self.meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participant)

        with self.assertRaises(RuntimeError):
            convene_meeting(meeting, actor=self.user)

        meeting.refresh_from_db()
        self.assertIsNone(meeting.convocada_at)
        notify.assert_not_called()
        email.assert_not_called()

    @patch("tareas.services.meetings.send_task_email", side_effect=RuntimeError("email"))
    @patch("tareas.services.meetings.notify_task_event", side_effect=RuntimeError("notify"))
    def test_convene_communication_failures_do_not_rollback(
        self, notify, email
    ):
        meeting = self.meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participant)

        with self.captureOnCommitCallbacks(execute=True):
            convene_meeting(meeting, actor=self.user)

        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.convocada_at)
        notify.assert_called_once()
        email.assert_called_once()

    def test_completion_requires_comments(self):
        meeting = self.meeting()
        item = add_task_to_meeting(reunion=meeting, tarea=self.task(), orden=1)
        with self.assertRaises(ValidationError):
            mark_meeting_completed(meeting)
        mark_meeting_completed(meeting, comentarios={item.pk: "Revisado"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.estado, ReunionRevision.Estado.REALIZADA)


class MeetingPermissionViewTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="00", descripcion="Empresa base")
        self.user = User.objects.create_user(username="meeting_view_user")
        self.tareas_vista = Vista.objects.create(nombre="Tareas")
        self.tareas_permiso = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.tareas_vista,
            ver=True,
            ingresar=True,
            crear=True,
            modificar=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def _create_meeting_view_permission(self, **flags):
        vista, _created = Vista.objects.get_or_create(
            nombre="Tareas - Reuniones",
            defaults={"route_name": "tareas:reunion_revision_lista"},
        )
        values = {
            "ver": True,
            "ingresar": False,
            "crear": False,
            "modificar": False,
        }
        values.update(flags)
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            **values,
        )

    def test_missing_registered_view_fails_closed_without_creating_it(self):
        permissions_before = Permiso.objects.count()

        response = self.client.get(reverse("tareas:reunion_revision_lista"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Vista.objects.filter(nombre="Tareas - Reuniones").exists()
        )
        self.assertEqual(Permiso.objects.count(), permissions_before)

    def test_list_and_edit_use_meeting_permissions_not_tasks_permissions(self):
        meeting_permission = self._create_meeting_view_permission(
            ingresar=False,
            modificar=False,
        )

        response = self.client.get(reverse("tareas:reunion_revision_lista"))
        self.assertEqual(response.status_code, 403)

        meeting_permission.ingresar = True
        meeting_permission.save(update_fields=["ingresar"])
        self.tareas_permiso.ingresar = False
        self.tareas_permiso.save(update_fields=["ingresar"])
        with patch("tareas.views.resolve_meeting_storage") as resolve_storage:
            resolve_storage.return_value.list_meetings.return_value = []
            response = self.client.get(reverse("tareas:reunion_revision_lista"))
        self.assertEqual(response.status_code, 200)

        self.tareas_permiso.modificar = True
        self.tareas_permiso.save(update_fields=["modificar"])
        response = self.client.get(
            reverse("tareas:reunion_revision_editar", args=(999999,))
        )
        self.assertEqual(response.status_code, 403)

    def test_create_view_requires_both_create_permissions(self):
        meeting_permission = self._create_meeting_view_permission(
            crear=True,
        )
        self.tareas_permiso.crear = False
        self.tareas_permiso.save(update_fields=["crear"])
        permissions_before = Permiso.objects.count()

        response = self.client.post(reverse("tareas:reunion_revision_crear"), {})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(Tarea.objects.exists())
        self.assertEqual(Permiso.objects.count(), permissions_before)

        self.tareas_permiso.crear = True
        self.tareas_permiso.save(update_fields=["crear"])
        meeting_permission.crear = False
        meeting_permission.save(update_fields=["crear"])
        response = self.client.post(reverse("tareas:reunion_revision_crear"), {})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(Tarea.objects.exists())

    def test_create_view_creates_department_meeting_and_planned_task(self):
        self._create_meeting_view_permission(crear=True)
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={"source_type": "DJANGO", "django_alias": "default"},
        )
        departamento = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-00-HTTP",
            nombre="Departamento HTTP",
            source=OrganizationalSource.LOCAL,
        )

        response = self.client.post(
            reverse("tareas:reunion_revision_crear"),
            {
                "titulo": "Reunión por Departamento",
                "descripcion": "Creación desde la vista",
                "fecha_hora_programada": "2026-10-28T10:00",
                "modalidad": ReunionRevision.Modalidad.ZOOM,
                "lugar_o_enlace": "",
                "tipo_ambito": ReunionRevision.TipoAmbito.DEPARTAMENTO,
                "local": "",
                "departamento": str(departamento.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        reunion = ReunionRevision.objects.get(titulo="Reunión por Departamento")
        self.assertEqual(reunion.empresa_id, self.empresa.pk)
        self.assertEqual(
            reunion.tipo_ambito,
            ReunionRevision.TipoAmbito.DEPARTAMENTO,
        )
        self.assertIsNone(reunion.local_id)
        self.assertEqual(reunion.departamento_id, departamento.pk)
        self.assertEqual(reunion.tarea_planificada.empresa_id, self.empresa.pk)
        self.assertEqual(
            reunion.tarea_planificada.tipo_ambito,
            Tarea.Ambito.DEPARTAMENTO,
        )
        self.assertIsNone(reunion.tarea_planificada.local_id)
        self.assertEqual(
            reunion.tarea_planificada.departamento_id,
            departamento.pk,
        )
        self.assertEqual(
            reunion.tarea_planificada.estado,
            Tarea.Estado.ACTIVA,
        )

    def test_create_without_active_company_is_denied(self):
        self._create_meeting_view_permission(crear=True)
        session = self.client.session
        session.pop("empresa_id", None)
        session.save()

        with patch("tareas.views.create_meeting") as create:
            get_response = self.client.get(
                reverse("tareas:reunion_revision_crear")
            )
            post_response = self.client.post(
                reverse("tareas:reunion_revision_crear"),
                {},
            )

        self.assertIn(get_response.status_code, {302, 403, 404})
        self.assertIn(post_response.status_code, {302, 403, 404})
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(Tarea.objects.exists())
        create.assert_not_called()

    def test_create_form_html_only_exposes_active_scope_in_active_company(self):
        self._create_meeting_view_permission(crear=True)
        local = Local.objects.create(
            empresa=self.empresa,
            codigo="LOC-00-A",
            nombre="Local activo A",
            source=OrganizationalSource.LOCAL,
        )
        departamento = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-00-A",
            nombre="Departamento activo A",
            source=OrganizationalSource.LOCAL,
        )
        Local.objects.create(
            empresa=self.empresa,
            codigo="LOC-00-X",
            nombre="Local inactivo A",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )
        Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-00-X",
            nombre="Departamento inactivo A",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )
        otra_empresa = Empresa.objects.create(
            codigo="01",
            descripcion="Otra empresa",
        )
        Local.objects.create(
            empresa=otra_empresa,
            codigo="LOC-01",
            nombre="Local empresa B",
            source=OrganizationalSource.LOCAL,
        )
        Departamento.objects.create(
            empresa=otra_empresa,
            codigo="DEP-01",
            nombre="Departamento empresa B",
            source=OrganizationalSource.LOCAL,
        )

        response = self.client.get(reverse("tareas:reunion_revision_crear"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(local))
        self.assertContains(response, str(departamento))
        self.assertNotContains(response, "Local inactivo A")
        self.assertNotContains(response, "Departamento inactivo A")
        self.assertNotContains(response, "Local empresa B")
        self.assertNotContains(response, "Departamento empresa B")

    def test_create_post_rejects_foreign_scope_id_without_creating_records(self):
        self._create_meeting_view_permission(crear=True)
        otra_empresa = Empresa.objects.create(
            codigo="01",
            descripcion="Otra empresa",
        )
        foreign_local = Local.objects.create(
            empresa=otra_empresa,
            codigo="LOC-01",
            nombre="Local empresa B",
            source=OrganizationalSource.LOCAL,
        )
        payload = {
            "titulo": "",
            "descripcion": "",
            "fecha_hora_programada": "2026-10-28T10:00",
            "modalidad": ReunionRevision.Modalidad.ZOOM,
            "lugar_o_enlace": "",
            "tipo_ambito": ReunionRevision.TipoAmbito.LOCAL,
            "local": str(foreign_local.pk),
            "departamento": "",
        }

        with patch("tareas.views.create_meeting") as create:
            response = self.client.post(
                reverse("tareas:reunion_revision_crear"),
                payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("local", response.context["form"].errors)
        local_errors = response.context["form"].errors.as_data()["local"]
        self.assertEqual(len(local_errors), 1)
        self.assertEqual(
            local_errors[0].message,
            "tareas.meetings.errors.selection_invalid",
        )
        self.assertIn("titulo", response.context["form"].errors)
        self.assertContains(
            response,
            'data-key="tareas.meetings.errors.selection_invalid"',
        )
        self.assertEqual(
            response.content.decode().count(
                'data-key="tareas.meetings.errors.selection_invalid"'
            ),
            1,
        )
        self.assertContains(
            response,
            "La selección no está disponible para la Empresa activa.",
        )
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(Tarea.objects.exists())
        create.assert_not_called()

    def test_create_view_renders_service_error_as_translatable_key(self):
        self._create_meeting_view_permission(crear=True)
        local = Local.objects.create(
            empresa=self.empresa,
            codigo="LOC-00-A",
            nombre="Local activo A",
            source=OrganizationalSource.LOCAL,
        )
        payload = {
            "titulo": "Reunión de prueba",
            "descripcion": "",
            "fecha_hora_programada": "2026-10-28T10:00",
            "modalidad": ReunionRevision.Modalidad.ZOOM,
            "lugar_o_enlace": "",
            "tipo_ambito": ReunionRevision.TipoAmbito.LOCAL,
            "local": str(local.pk),
            "departamento": "",
        }
        error_key = "tareas.meetings.errors.local_inactive"

        with patch(
            "tareas.views.create_meeting",
            side_effect=ValidationError(error_key, code=error_key),
        ):
            response = self.client.post(
                reverse("tareas:reunion_revision_crear"),
                payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-key="{error_key}"')
        self.assertContains(
            response,
            "El Local está inactivo y no puede asignarse a una reunión nueva.",
        )
