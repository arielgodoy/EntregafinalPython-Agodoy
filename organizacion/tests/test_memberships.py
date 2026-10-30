import uuid
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from organizacion.models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    MembresiaDepartamental,
    OrganizationalSource,
)
from organizacion.services import memberships


class MembershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="71", descripcion="Empresa A")
        cls.other_empresa = Empresa.objects.create(codigo="72", descripcion="Empresa B")
        cls.department = cls.make_department(cls.empresa, "A")
        cls.second_department = cls.make_department(cls.empresa, "B")
        cls.other_department = cls.make_department(cls.other_empresa, "A")
        cls.user = get_user_model().objects.create_user(username="member")
        cls.other_user = get_user_model().objects.create_user(username="replacement")
        cls.profile = PerfilAcceso.objects.create(nombre="Membership fixtures")
        for user in (cls.user, cls.other_user):
            UsuarioPerfilEmpresa.objects.create(
                usuario=user, empresa=cls.empresa, perfil=cls.profile
            )

    @staticmethod
    def make_department(empresa, codigo):
        return Departamento.objects.create(
            empresa=empresa, codigo=codigo, nombre=codigo, source=OrganizationalSource.LOCAL
        )

    def member(self, **overrides):
        values = dict(
            empresa=self.empresa, departamento=self.department, usuario=self.user,
            rol=MembresiaDepartamental.Rol.STAFF,
        )
        values.update(overrides)
        return MembresiaDepartamental.objects.create(**values)

    def event(self, member, **overrides):
        values = dict(
            membresia=member, empresa=member.empresa, departamento=member.departamento,
            usuario_afectado=member.usuario, autor=self.other_user,
            operacion_id=uuid.uuid4(), secuencia=1, tipo="ALTA", motivo="Alta autorizada",
            rol_despues=member.rol, estado_despues=member.estado, version_despues=member.version,
        )
        values.update(overrides)
        return EventoMembresia.objects.create(**values)

    def test_defaults_and_multiple_departments_and_companies(self):
        first = self.member()
        self.member(departamento=self.second_department)
        self.member(empresa=self.other_empresa, departamento=self.other_department)
        self.assertEqual(MembresiaDepartamental.objects.count(), 3)
        self.assertEqual(first.estado, "ACTIVA")
        self.assertEqual(first.version, 1)
        self.assertIsNotNone(first.created_at.tzinfo)
        self.assertNotIn("local", {f.name for f in Departamento._meta.fields})

    def test_triple_is_unique_even_after_suspension_or_baja(self):
        for state in ("ACTIVA", "SUSPENDIDA", "BAJA"):
            with self.subTest(state=state):
                member = self.member(estado=state, departamento=self.make_department(self.empresa, state))
                duplicate = MembresiaDepartamental(
                    empresa=member.empresa, departamento=member.departamento,
                    usuario=member.usuario, rol="STAFF",
                )
                with self.assertRaises(IntegrityError), transaction.atomic():
                    models.Model.save(duplicate)

    def test_head_constraint_does_not_depend_on_department_activity(self):
        self.department.activo = False
        self.department.save(update_fields=["activo"])
        self.member(rol="JEFE")
        duplicate = MembresiaDepartamental(
            empresa=self.empresa, departamento=self.department, usuario=self.other_user, rol="JEFE"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.Model.save(duplicate)
        self.assertEqual(MembresiaDepartamental.objects.get(rol="JEFE").usuario_id, self.user.pk)

    def test_multiple_supervisors_and_staff_are_allowed(self):
        for role, department in (("SUPERVISOR", self.department), ("STAFF", self.second_department)):
            self.member(rol=role, departamento=department)
            self.member(rol=role, departamento=department, usuario=self.other_user)
        self.assertEqual(MembresiaDepartamental.objects.count(), 4)

    def test_inactive_head_does_not_reserve_active_position(self):
        self.member(rol="JEFE", estado="SUSPENDIDA")
        self.member(rol="JEFE", usuario=self.other_user)
        self.assertEqual(MembresiaDepartamental.objects.filter(rol="JEFE", estado="ACTIVA").count(), 1)

    def test_invalid_company_role_state_and_version_are_rejected(self):
        for overrides in (
            {"departamento": self.other_department}, {"rol": "ADMIN"},
            {"estado": "INACTIVA"}, {"version": 0},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.member(**overrides)

    def test_identity_and_version_cannot_regress(self):
        member = self.member(version=3)
        member.version = 2
        with self.assertRaises(ValidationError):
            member.save()
        member.version = 3
        member.empresa = self.other_empresa
        member.departamento = self.other_department
        with self.assertRaises(ValidationError):
            member.save()

    def test_history_survives_state_changes_and_identity_is_reused(self):
        member = self.member()
        event = self.event(member)
        for version, state in enumerate(("SUSPENDIDA", "BAJA", "ACTIVA"), start=2):
            member.estado = state
            member.version = version
            member.save()
        member.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual((event.estado_despues, event.version_despues), ("ACTIVA", 1))
        self.assertEqual((member.estado, member.version), ("ACTIVA", 4))

    def test_event_requires_reason_and_matching_references(self):
        member = self.member()
        for overrides in (
            {"motivo": "   "}, {"empresa": self.other_empresa},
            {"usuario_afectado": self.other_user}, {"departamento": self.other_department},
            {"version_antes": 3, "rol_antes": "STAFF", "estado_antes": "ACTIVA", "version_despues": 2},
            {"version_antes": 1, "rol_antes": "", "estado_antes": "", "version_despues": 2},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.event(member, **overrides)

    def test_events_are_append_only_and_operation_sequence_unique(self):
        member = self.member()
        event = self.event(member)
        for operation in (
            lambda: event.save(),
            lambda: event.delete(),
            lambda: EventoMembresia.objects.filter(pk=event.pk).update(motivo="Changed"),
            lambda: EventoMembresia.objects.filter(pk=event.pk).delete(),
            lambda: self.event(member, operacion_id=event.operacion_id, secuencia=event.secuencia),
        ):
            with self.assertRaises(ValidationError):
                operation()
        self.event(member, operacion_id=event.operacion_id, secuencia=2)
        self.assertEqual(EventoMembresia.objects.count(), 2)

    def test_membership_delete_and_bulk_writes_are_rejected(self):
        member = self.member()
        for operation in (
            lambda: member.delete(),
            lambda: MembresiaDepartamental.objects.all().delete(),
            lambda: MembresiaDepartamental.objects.all().update(empresa=self.other_empresa),
            lambda: MembresiaDepartamental.objects.bulk_create([member]),
        ):
            with self.assertRaises(ValidationError):
                operation()

    def test_foreign_keys_are_protected(self):
        self.event(self.member())
        for obj in (self.empresa, self.department, self.user, self.other_user):
            with self.assertRaises(ProtectedError):
                obj.delete()

    def test_coordination_has_one_row_per_company_and_no_implicit_creation(self):
        ControlOrganizacionEmpresa.objects.create(empresa=self.empresa)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ControlOrganizacionEmpresa.objects.create(empresa=self.empresa)
        self.assertFalse(ControlOrganizacionEmpresa.objects.filter(empresa=self.other_empresa).exists())

    def test_queries_are_scoped_materialized_and_do_not_create_fence(self):
        member = self.member()
        self.member(empresa=self.other_empresa, departamento=self.other_department)
        rows = memberships.list_memberships(empresa_id=self.empresa.pk)
        self.assertEqual([row.id for row in rows], [member.pk])
        with self.assertNumQueries(0):
            self.assertEqual(rows[0].usuario_id, self.user.pk)
        with self.assertRaises(FrozenInstanceError):
            setattr(rows[0], "estado", "BAJA")
        self.assertEqual(ControlOrganizacionEmpresa.objects.count(), 0)
        self.assertEqual(
            memberships.list_memberships(
                empresa_id=self.empresa.pk, department_id=self.second_department.pk
            ), (),
        )

    def test_effectiveness_and_recovery_follow_current_facts_without_changing_membership(self):
        member = self.member()
        for version, state in enumerate(("SUSPENDIDA", "BAJA", "ACTIVA"), start=2):
            member.estado, member.version = state, version
            member.save()
            result = memberships.check_department_eligibility(empresa_id=self.empresa.pk, user_id=self.user.pk)
            self.assertEqual(result.elegible, state == "ACTIVA")
        self.department.activo = False
        self.department.save(update_fields=["activo"])
        self.assertNotIn(
            self.department.pk,
            {row.id for row in memberships.list_active_departments(empresa_id=self.empresa.pk)},
        )
        self.assertFalse(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)
        member.refresh_from_db()
        self.assertEqual(member.estado, "ACTIVA")
        self.department.activo = True
        self.department.save(update_fields=["activo"])
        self.assertTrue(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)

    def test_any_effective_department_suffices_and_other_company_does_not(self):
        self.member(estado="SUSPENDIDA")
        active = self.member(departamento=self.second_department)
        result = memberships.get_effective_memberships(empresa_id=self.empresa.pk, user_id=self.user.pk)
        self.assertEqual([row.id for row in result.memberships], [active.pk])
        self.assertIsNone(result.revision)
        self.assertFalse(memberships.check_department_eligibility(
            empresa_id=self.other_empresa.pk, user_id=self.user.pk
        ).elegible)
        UsuarioPerfilEmpresa.objects.create(
            usuario=self.user, empresa=self.other_empresa, perfil=self.profile
        )
        other = self.member(empresa=self.other_empresa, departamento=self.other_department)
        self.assertTrue(memberships.check_department_eligibility(
            empresa_id=self.other_empresa.pk, user_id=self.user.pk
        ).elegible)
        self.assertEqual(
            [row.id for row in memberships.get_effective_memberships(
                empresa_id=self.empresa.pk, user_id=self.user.pk
            ).memberships],
            [active.pk],
        )
        self.assertEqual(
            [row.id for row in memberships.list_memberships(
                empresa_id=self.other_empresa.pk, user_id=self.user.pk
            )],
            [other.pk],
        )

    def test_access_uses_official_union_not_vicmeas_action_flags(self):
        self.member(rol="JEFE")
        UsuarioPerfilEmpresa.objects.filter(usuario=self.user).delete()
        self.assertFalse(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)
        vista = Vista.objects.create(nombre="Membership fixture")
        Permiso.objects.create(usuario=self.user, empresa=self.empresa, vista=vista)
        self.assertTrue(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertFalse(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=True)
        self.assertTrue(memberships.check_department_eligibility(
            empresa_id=self.empresa.pk, user_id=self.user.pk
        ).elegible)

    def test_no_membership_is_normal_and_revision_is_materialized(self):
        ControlOrganizacionEmpresa.objects.create(empresa=self.empresa, version=7)
        result = memberships.check_department_eligibility(empresa_id=self.empresa.pk, user_id=self.user.pk)
        self.assertFalse(result.elegible)
        self.assertEqual(result.causas, ("NO_EFFECTIVE_MEMBERSHIP",))
        self.assertEqual(result.revision, 7)
        self.assertEqual(result.departamentos, ())

    def test_department_and_leadership_queries(self):
        with self.assertNoLogs("organizacion", level="WARNING"):
            result = memberships.get_department_leadership(
                empresa_id=self.empresa.pk, department_id=self.department.pk
            )
        self.assertIsNone(result.jefe)
        self.assertEqual(result.supervisores, ())
        self.member(rol="JEFE")
        supervisor = self.member(rol="SUPERVISOR", usuario=self.other_user)
        result = memberships.get_department_leadership(
            empresa_id=self.empresa.pk, department_id=self.department.pk
        )
        assert result.jefe is not None
        self.assertEqual(result.jefe.usuario_id, self.user.pk)
        self.assertEqual(result.supervisores[0].id, supervisor.pk)
        self.assertEqual(
            {row.id for row in memberships.list_active_departments(empresa_id=self.empresa.pk)},
            {self.department.pk, self.second_department.pk},
        )

    def test_cross_company_and_invalid_context_are_explicit_errors(self):
        for value in (None, True, 0, "71"):
            with self.subTest(value=value):
                self.assertRaises(
                    memberships.OrganizationInputError,
                    memberships.list_active_departments, empresa_id=value,
                )
        with self.assertRaises(memberships.OrganizationNotFoundError):
            memberships.list_memberships(empresa_id=self.empresa.pk, department_id=self.other_department.pk)
        with self.assertRaises(memberships.OrganizationNotFoundError):
            memberships.get_effective_memberships(empresa_id=self.empresa.pk, user_id=999999)

    def test_unavailability_is_sanitized_not_an_empty_list(self):
        with patch.object(Empresa.objects, "using", side_effect=OperationalError("sensitive connection data")):
            with self.assertLogs("organizacion.services.memberships", level="ERROR") as logged:
                with self.assertRaises(memberships.OrganizationUnavailableError) as error:
                    memberships.list_active_departments(empresa_id=self.empresa.pk)
        self.assertNotIn("sensitive", str(error.exception))
        self.assertNotIn("sensitive", str(logged.output))

    def test_database_checks_reject_invalid_values_without_model_validation(self):
        for field, value in (("rol", "ADMIN"), ("estado", "INACTIVA"), ("version", 0)):
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                member = MembresiaDepartamental(
                    empresa=self.empresa, departamento=self.department, usuario=self.user, rol="STAFF"
                )
                setattr(member, field, value)
                models.Model.save(member)

    def test_no_membership_writes_are_allowed_on_other_aliases(self):
        member = MembresiaDepartamental(
            empresa=self.empresa, departamento=self.department, usuario=self.user, rol="STAFF"
        )
        with self.assertRaises(ValidationError):
            member.save(using="system_test")
        member._state.db = "system_test"
        with self.assertRaises(ValidationError):
            member.save(using="default")
        with self.assertRaises(ValidationError):
            ControlOrganizacionEmpresa(empresa=self.empresa).save(using="system_test")
        self.assertEqual(MembresiaDepartamental.objects.count(), 0)

    def test_public_queries_only_read(self):
        self.member()
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            memberships.list_active_departments(empresa_id=self.empresa.pk)
            memberships.list_memberships(empresa_id=self.empresa.pk, user_id=self.user.pk)
            memberships.get_effective_memberships(empresa_id=self.empresa.pk, user_id=self.user.pk)
            memberships.check_department_eligibility(empresa_id=self.empresa.pk, user_id=self.user.pk)
            memberships.get_department_leadership(
                empresa_id=self.empresa.pk, department_id=self.department.pk
            )
        self.assertTrue(captured.captured_queries)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in captured))


class MembershipMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_catalogs_without_backfill(self):
        before = [("organizacion", "0001_initial")]
        after = [("organizacion", "0002_department_memberships")]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            company = apps.get_model("access_control", "Empresa").objects.create(codigo="79")
            department = apps.get_model("organizacion", "Departamento").objects.create(
                empresa_id=company.pk, codigo="OLD", nombre="Original", source="LOCAL"
            )
            local = apps.get_model("organizacion", "Local").objects.create(
                empresa_id=company.pk, codigo="OLD", nombre="Original local", source="ERP", legacy_code="L1"
            )
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            self.assertEqual(
                apps.get_model("organizacion", "Departamento").objects.values_list(
                    "nombre", flat=True
                ).get(pk=department.pk),
                "Original",
            )
            self.assertEqual(
                apps.get_model("organizacion", "Local").objects.values_list(
                    "legacy_code", flat=True
                ).get(pk=local.pk), "L1"
            )
            for name in ("MembresiaDepartamental", "EventoMembresia", "ControlOrganizacionEmpresa"):
                self.assertEqual(apps.get_model("organizacion", name).objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(after)
