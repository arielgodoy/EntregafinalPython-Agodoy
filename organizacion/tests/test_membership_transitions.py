from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from auditoria.models import AuditoriaOrganizacionEvent
from organizacion.models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    MembresiaDepartamental,
    OrganizationalSource,
)
from organizacion.services.memberships import (
    MembershipCommand,
    MembershipCommandResult,
    MembershipConflict,
    MembershipOperation,
    MembershipPermissionDenied,
    OrganizationInputError,
    OrganizationNotFoundError,
    OrganizationUnavailableError,
    change_membership,
    get_membership_history,
)


User = get_user_model()
MASTER_VIEW = "Tareas - Maestro de departamentos"


class MembershipCommandServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="81", descripcion="Empresa de T176")
        cls.other_empresa = Empresa.objects.create(codigo="82", descripcion="Empresa aislada")
        cls.departamento = Departamento.objects.create(
            empresa=cls.empresa,
            codigo="T176",
            nombre="Departamento T176",
            source=OrganizationalSource.LOCAL,
        )
        cls.other_departamento = Departamento.objects.create(
            empresa=cls.other_empresa,
            codigo="T176B",
            nombre="Departamento ajeno",
            source=OrganizationalSource.LOCAL,
        )
        cls.actor = User.objects.create_user(username="t176-actor", password="test")
        cls.usuario = User.objects.create_user(username="t176-user", password="test")
        cls.segundo_usuario = User.objects.create_user(username="t176-user-2", password="test")
        cls.usuario_ajeno = User.objects.create_user(username="t176-user-other", password="test")
        cls.actor_ajeno = User.objects.create_user(username="t176-actor-other", password="test")
        cls.jefe_sin_permiso = User.objects.create_user(
            username="t176-jefe-no-admin", password="test"
        )
        cls.sin_permiso_lectura = User.objects.create_user(
            username="t176-no-reader", password="test"
        )

        cls.vista = Vista.objects.create(nombre=MASTER_VIEW)
        cls._grant_company(cls.actor, cls.empresa)
        cls._grant_company(cls.usuario, cls.empresa)
        cls._grant_company(cls.segundo_usuario, cls.empresa)
        cls._grant_company(cls.jefe_sin_permiso, cls.empresa)
        cls._grant_company(cls.sin_permiso_lectura, cls.empresa)
        cls._grant_company(cls.usuario_ajeno, cls.other_empresa)
        cls._grant_company(cls.actor_ajeno, cls.other_empresa)
        cls._grant_actions(
            cls.actor,
            cls.empresa,
            crear=True,
            modificar=True,
            eliminar=True,
            ingresar=True,
        )
        cls._grant_actions(
            cls.segundo_usuario,
            cls.empresa,
            crear=True,
            modificar=True,
            eliminar=True,
            ingresar=True,
        )
        cls._grant_actions(
            cls.actor_ajeno,
            cls.other_empresa,
            crear=True,
            modificar=True,
            eliminar=True,
            ingresar=True,
        )
        cls._grant_actions(
            cls.sin_permiso_lectura,
            cls.empresa,
            modificar=True,
        )

    @staticmethod
    def _grant_company(user, empresa):
        profile = PerfilAcceso.objects.create(
            nombre=f"Perfil {empresa.codigo} usuario {user.pk}"
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=user,
            empresa=empresa,
            perfil=profile,
            asignado_por=user,
        )

    @classmethod
    def _grant_actions(
        cls,
        user,
        empresa,
        *,
        crear=False,
        modificar=False,
        eliminar=False,
        ingresar=False,
    ):
        Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=cls.vista,
            crear=crear,
            modificar=modificar,
            eliminar=eliminar,
            ingresar=ingresar,
        )

    def command(self, **overrides):
        values = {
            "company_id": self.empresa.pk,
            "actor_id": self.actor.pk,
            "user_id": self.usuario.pk,
            "department_id": self.departamento.pk,
            "operation_id": uuid4(),
            "action": MembershipOperation.CREATE,
            "reason": "Alta autorizada para prueba",
            "target_role": "STAFF",
            "expected_membership_version": None,
            "expected_organization_revision": None,
        }
        values.update(overrides)
        return MembershipCommand(**values)

    def next_command(self, result, *, action, **overrides):
        values = {
            "company_id": result.company_id,
            "actor_id": self.actor.pk,
            "user_id": result.user_id,
            "department_id": result.department_id,
            "operation_id": uuid4(),
            "action": action,
            "reason": f"Operación {action.value}",
            "target_role": None,
            "expected_membership_version": result.membership_version,
            "expected_organization_revision": result.organization_revision,
        }
        values.update(overrides)
        return MembershipCommand(**values)

    def create_membership(self, **overrides):
        return change_membership(self.command(**overrides))

    def test_create_persists_membership_history_revision_and_central_audit(self):
        result = self.create_membership()

        self.assertIsInstance(result, MembershipCommandResult)
        self.assertFalse(result.replayed)
        self.assertEqual(
            (result.company_id, result.department_id, result.user_id),
            (self.empresa.pk, self.departamento.pk, self.usuario.pk),
        )
        self.assertEqual(
            (result.role, result.state, result.membership_version, result.organization_revision),
            ("STAFF", "ACTIVA", 1, 2),
        )
        member = MembresiaDepartamental.objects.get(pk=result.membership_id)
        self.assertEqual(member._state.db, "default")
        self.assertEqual((member.rol, member.estado, member.version), ("STAFF", "ACTIVA", 1))

        event = EventoMembresia.objects.get(pk=result.event_id)
        self.assertEqual(event._state.db, "default")
        self.assertEqual(event.operacion_id, result.operation_id)
        self.assertEqual(event.tipo, "ALTA")
        self.assertEqual(event.autor_id, self.actor.pk)
        self.assertEqual(event.motivo, "Alta autorizada para prueba")
        self.assertIsNone(event.version_antes)
        self.assertEqual((event.rol_despues, event.estado_despues, event.version_despues),
                         ("STAFF", "ACTIVA", 1))
        self.assertIsNone(event.revision_organizacion_esperada)
        self.assertEqual(event.revision_organizacion, 2)
        assert event.huella_solicitud is not None
        self.assertRegex(event.huella_solicitud, r"^[0-9a-f]{64}$")
        self.assertEqual(
            ControlOrganizacionEmpresa.objects.get(empresa=self.empresa).version,
            2,
        )

        audit = AuditoriaOrganizacionEvent.objects.get()
        self.assertEqual(audit._state.db, "default")
        assert audit.user is not None
        self.assertEqual(
            (audit.user.pk, audit.empresa_id, audit.action),
            (self.actor.pk, self.empresa.pk, "CREATE"),
        )
        self.assertEqual((audit.object_type, audit.object_id),
                         ("MembresiaDepartamental", str(member.pk)))
        assert audit.meta is not None
        assert audit.after is not None
        self.assertEqual(audit.meta["reason"], "Alta autorizada para prueba")
        self.assertEqual(audit.meta["operation_id"], str(result.operation_id))
        self.assertEqual(audit.after["version"], 1)

    def test_duplicate_identity_is_rejected_without_new_effects(self):
        first = self.create_membership()
        duplicate = self.command(
            expected_organization_revision=first.organization_revision,
        )

        with self.assertRaises(MembershipConflict):
            change_membership(duplicate)

        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_role_change_records_expected_and_resulting_versions(self):
        created = self.create_membership()
        command = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="SUPERVISOR",
        )

        result = change_membership(command)
        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        event = EventoMembresia.objects.get(pk=result.event_id)

        self.assertEqual((member.rol, member.estado, member.version), ("SUPERVISOR", "ACTIVA", 2))
        self.assertEqual((result.membership_version, result.organization_revision), (2, 3))
        self.assertEqual((event.rol_antes, event.rol_despues), ("STAFF", "SUPERVISOR"))
        self.assertEqual(event.version_antes, 1)
        self.assertEqual(event.revision_organizacion_esperada, 2)
        self.assertEqual(event.revision_organizacion, 3)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 2)

    def test_role_change_to_jefe_succeeds_when_the_department_has_no_active_head(self):
        created = self.create_membership()

        result = change_membership(self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="JEFE",
        ))

        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual((member.rol, member.estado, member.version), ("JEFE", "ACTIVA", 2))
        self.assertEqual(result.organization_revision, 3)
        self.assertEqual(
            MembresiaDepartamental.objects.filter(
                departamento=self.departamento,
                rol="JEFE",
                estado="ACTIVA",
            ).count(),
            1,
        )

    def test_jefe_is_allowed_when_vacant_but_second_active_head_is_rejected(self):
        first = self.create_membership(target_role="JEFE")
        second = self.command(
            user_id=self.segundo_usuario.pk,
            operation_id=uuid4(),
            target_role="JEFE",
            expected_organization_revision=first.organization_revision,
        )

        with self.assertRaises(MembershipConflict):
            change_membership(second)

        self.assertEqual(
            list(MembresiaDepartamental.objects.filter(
                departamento=self.departamento, rol="JEFE", estado="ACTIVA"
            ).values_list("usuario_id", flat=True)),
            [self.usuario.pk],
        )
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_role_change_never_replaces_an_existing_active_head(self):
        self.create_membership(target_role="JEFE")
        other_member = MembresiaDepartamental.objects.create(
            empresa=self.empresa,
            departamento=self.departamento,
            usuario=self.segundo_usuario,
            rol="STAFF",
        )
        command = MembershipCommand(
            company_id=self.empresa.pk,
            actor_id=self.actor.pk,
            user_id=self.segundo_usuario.pk,
            department_id=self.departamento.pk,
            operation_id=uuid4(),
            action=MembershipOperation.CHANGE_ROLE,
            reason="No reemplazar al JEFE de forma implícita",
            target_role="JEFE",
            expected_membership_version=other_member.version,
            expected_organization_revision=2,
        )

        with self.assertRaises(MembershipConflict):
            change_membership(command)

        other_member.refresh_from_db()
        self.assertEqual((other_member.rol, other_member.version), ("STAFF", 1))
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_suspend_reactivate_and_logical_baja_preserve_one_identity(self):
        created = self.create_membership()
        suspended = change_membership(self.next_command(
            created, action=MembershipOperation.SUSPEND
        ))
        reactivated = change_membership(self.next_command(
            suspended, action=MembershipOperation.REACTIVATE
        ))
        baja = change_membership(self.next_command(
            reactivated, action=MembershipOperation.LOGICAL_DELETE
        ))

        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual((member.estado, member.version), ("BAJA", 4))
        self.assertEqual(baja.organization_revision, 5)
        self.assertEqual(EventoMembresia.objects.count(), 4)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 4)
        self.assertEqual(
            list(EventoMembresia.objects.order_by("secuencia", "pk").values_list(
                "estado_antes", "estado_despues", "version_antes", "version_despues"
            )),
            [
                (None, "ACTIVA", None, 1),
                ("ACTIVA", "SUSPENDIDA", 1, 2),
                ("SUSPENDIDA", "ACTIVA", 2, 3),
                ("ACTIVA", "BAJA", 3, 4),
            ],
        )
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 5)

    def test_role_change_on_suspended_member_keeps_it_suspended(self):
        created = self.create_membership()
        suspended = change_membership(self.next_command(
            created, action=MembershipOperation.SUSPEND
        ))

        changed = change_membership(self.next_command(
            suspended,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="SUPERVISOR",
        ))

        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual((member.rol, member.estado, member.version),
                         ("SUPERVISOR", "SUSPENDIDA", 3))
        self.assertEqual((changed.state, changed.membership_version), ("SUSPENDIDA", 3))

    def test_invalid_or_noop_transitions_are_rejected(self):
        created = self.create_membership()
        suspended = change_membership(self.next_command(
            created, action=MembershipOperation.SUSPEND
        ))
        before = (
            MembresiaDepartamental.objects.get(pk=created.membership_id).version,
            ControlOrganizacionEmpresa.objects.get().version,
            EventoMembresia.objects.count(),
            AuditoriaOrganizacionEvent.objects.count(),
        )

        invalid_commands = (
            self.next_command(suspended, action=MembershipOperation.SUSPEND),
            self.next_command(created, action=MembershipOperation.REACTIVATE),
            self.next_command(
                suspended,
                action=MembershipOperation.CHANGE_ROLE,
                target_role="STAFF",
            ),
        )
        for command in invalid_commands:
            with self.subTest(action=command.action, target_role=command.target_role):
                with self.assertRaises(MembershipConflict):
                    change_membership(command)
        with self.assertRaises(OrganizationInputError):
            change_membership(self.next_command(
                suspended,
                action=MembershipOperation.CHANGE_ROLE,
                target_role="INVALID",
            ))

        self.assertEqual(
            (
                MembresiaDepartamental.objects.get(pk=created.membership_id).version,
                ControlOrganizacionEmpresa.objects.get().version,
                EventoMembresia.objects.count(),
                AuditoriaOrganizacionEvent.objects.count(),
            ),
            before,
        )

    def test_stale_membership_and_organization_versions_conflict_without_overwrite(self):
        created = self.create_membership()
        valid = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="SUPERVISOR",
        )
        changed = change_membership(valid)
        stale_membership = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="JEFE",
            expected_organization_revision=changed.organization_revision,
        )
        stale_organization = self.next_command(
            changed,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="JEFE",
            expected_organization_revision=created.organization_revision,
        )

        for command in (stale_membership, stale_organization):
            with self.subTest(
                expected_membership=command.expected_membership_version,
                expected_organization=command.expected_organization_revision,
            ), self.assertRaises(MembershipConflict):
                change_membership(command)

        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual((member.rol, member.version), ("SUPERVISOR", 2))
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 3)
        self.assertEqual(EventoMembresia.objects.count(), 2)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 2)

    def test_first_control_revision_is_distinct_from_an_existing_revision(self):
        command = self.command(expected_organization_revision=1)
        with self.assertRaises(MembershipConflict):
            change_membership(command)
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(MembresiaDepartamental.objects.exists())

        ControlOrganizacionEmpresa.objects.create(empresa=self.empresa, version=7)
        valid = self.command(
            expected_organization_revision=7,
            operation_id=uuid4(),
        )
        result = change_membership(valid)
        self.assertEqual(result.organization_revision, 8)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 8)

    def test_create_and_reactivate_require_active_user_access_and_same_company(self):
        no_access = self.command(user_id=self.usuario_ajeno.pk)
        wrong_department = self.command(department_id=self.other_departamento.pk)
        with self.assertRaises(MembershipConflict):
            change_membership(no_access)
        with self.assertRaises(OrganizationNotFoundError):
            change_membership(wrong_department)

        inactive_user = self.command(user_id=self.segundo_usuario.pk)
        User.objects.filter(pk=self.segundo_usuario.pk).update(is_active=False)
        with self.assertRaises(MembershipConflict):
            change_membership(inactive_user)
        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_invalid_command_fields_are_rejected_before_any_write(self):
        created = self.create_membership()
        invalid_commands = (
            replace(self.command(), reason="   "),
            replace(self.command(), operation_id="not-a-uuid"),
            replace(self.command(), action="UNKNOWN"),
            replace(self.command(), company_id=True),
            replace(
                self.next_command(created, action=MembershipOperation.SUSPEND),
                expected_membership_version=None,
            ),
            replace(
                self.next_command(created, action=MembershipOperation.SUSPEND),
                expected_organization_revision=0,
            ),
            replace(
                self.next_command(
                    created,
                    action=MembershipOperation.SUSPEND,
                ),
                target_role="STAFF",
            ),
        )
        before = (
            MembresiaDepartamental.objects.count(),
            EventoMembresia.objects.count(),
            ControlOrganizacionEmpresa.objects.get().version,
            AuditoriaOrganizacionEvent.objects.count(),
        )

        for command in invalid_commands:
            with self.subTest(operation_id=command.operation_id, action=command.action):
                with self.assertRaises(OrganizationInputError):
                    change_membership(command)

        self.assertEqual(
            (
                MembresiaDepartamental.objects.count(),
                EventoMembresia.objects.count(),
                ControlOrganizacionEmpresa.objects.get().version,
                AuditoriaOrganizacionEvent.objects.count(),
            ),
            before,
        )

    def test_member_without_current_company_access_may_only_be_logically_removed(self):
        created = self.create_membership()
        UsuarioPerfilEmpresa.objects.filter(
            usuario=self.usuario, empresa=self.empresa
        ).delete()

        suspend = self.next_command(created, action=MembershipOperation.SUSPEND)
        with self.assertRaises(MembershipConflict):
            change_membership(suspend)

        removed = change_membership(self.next_command(
            created, action=MembershipOperation.LOGICAL_DELETE
        ))
        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual((removed.state, member.estado), ("BAJA", "BAJA"))

    def test_actor_must_have_company_access_and_explicit_vicmeas_action(self):
        created = self.create_membership()
        role_only_member = MembresiaDepartamental.objects.create(
            empresa=self.empresa,
            departamento=self.departamento,
            usuario=self.jefe_sin_permiso,
            rol="JEFE",
        )
        leader_command = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            actor_id=self.jefe_sin_permiso.pk,
            target_role="SUPERVISOR",
        )
        no_company_access = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            actor_id=self.actor_ajeno.pk,
            target_role="SUPERVISOR",
        )
        with self.assertRaises(MembershipPermissionDenied):
            change_membership(leader_command)
        with self.assertRaises(MembershipPermissionDenied):
            change_membership(no_company_access)

        denied_delete = self.next_command(
            created,
            action=MembershipOperation.LOGICAL_DELETE,
        )
        Permiso.objects.filter(
            usuario=self.actor, empresa=self.empresa, vista=self.vista
        ).update(eliminar=False)
        with self.assertRaises(MembershipPermissionDenied):
            change_membership(denied_delete)
        role_only_member.refresh_from_db()
        self.assertEqual((role_only_member.rol, role_only_member.estado), ("JEFE", "ACTIVA"))
        self.assertEqual(MembresiaDepartamental.objects.count(), 2)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_same_uuid_replays_original_result_without_reauditing(self):
        original_command = self.command()
        original = change_membership(original_command)
        later = change_membership(self.next_command(
            original,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="SUPERVISOR",
        ))
        UsuarioPerfilEmpresa.objects.filter(
            usuario=self.usuario, empresa=self.empresa
        ).delete()

        replay_command = replace(
            original_command,
            operation_id=str(original_command.operation_id).replace("-", "").upper(),
        )
        replay = change_membership(replay_command)

        self.assertTrue(replay.replayed)
        self.assertEqual(
            replace(replay, replayed=False),
            original,
        )
        member = MembresiaDepartamental.objects.get(pk=original.membership_id)
        self.assertEqual((member.rol, member.version), ("SUPERVISOR", 2))
        self.assertEqual((later.organization_revision, ControlOrganizacionEmpresa.objects.get().version),
                         (3, 3))
        self.assertEqual(EventoMembresia.objects.count(), 2)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 2)

    def test_legacy_event_without_fingerprint_is_not_accepted_as_replay(self):
        member = MembresiaDepartamental.objects.create(
            empresa=self.empresa,
            departamento=self.departamento,
            usuario=self.usuario,
            rol="STAFF",
        )
        operation_id = uuid4()
        EventoMembresia.objects.create(
            membresia=member,
            empresa=self.empresa,
            usuario_afectado=self.usuario,
            departamento=self.departamento,
            autor=self.actor,
            operacion_id=operation_id,
            secuencia=1,
            tipo="ALTA",
            motivo="Alta autorizada para prueba",
            rol_despues="STAFF",
            estado_despues="ACTIVA",
            version_despues=1,
        )
        command = self.command(operation_id=operation_id)

        with self.assertRaises(MembershipConflict):
            change_membership(command)

        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_same_uuid_with_different_payload_is_a_conflict(self):
        original_command = self.command()
        original = change_membership(original_command)
        changed_payloads = (
            replace(original_command, reason="Otro motivo"),
            replace(original_command, target_role="JEFE"),
            replace(original_command, actor_id=self.segundo_usuario.pk),
            replace(original_command, expected_organization_revision=7),
        )

        for changed in changed_payloads:
            with self.subTest(reason=changed.reason, role=changed.target_role):
                with self.assertRaises(MembershipConflict):
                    change_membership(changed)

        member = MembresiaDepartamental.objects.get(pk=original.membership_id)
        self.assertEqual((member.rol, member.version), ("STAFF", 1))
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_same_uuid_cannot_return_result_from_another_company(self):
        operation_id = uuid4()
        original = self.command(operation_id=operation_id)
        change_membership(original)
        foreign = self.command(
            company_id=self.other_empresa.pk,
            actor_id=self.actor_ajeno.pk,
            user_id=self.usuario_ajeno.pk,
            department_id=self.other_departamento.pk,
            operation_id=operation_id,
        )

        with self.assertRaises(MembershipConflict):
            change_membership(foreign)

        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_audit_none_rolls_back_membership_history_and_revision(self):
        with self.assertRaises(OrganizationUnavailableError):
            with self.assertLogs("organizacion.services.memberships", level="ERROR"):
                with self._audit_result(None):
                    change_membership(self.command())

        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_audit_database_exception_rolls_back_all_local_writes(self):
        with self.assertRaises(OrganizationUnavailableError):
            with self.assertLogs("organizacion.services.memberships", level="ERROR"):
                with self._audit_result(DatabaseError("sensitive database detail")):
                    change_membership(self.command())

        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_unexpected_audit_exception_is_sanitized_and_rolls_back(self):
        with self.assertRaises(OrganizationUnavailableError) as error:
            with self.assertLogs("organizacion.services.memberships", level="ERROR") as logged:
                with self._audit_result(RuntimeError("sensitive audit detail")):
                    change_membership(self.command())

        self.assertNotIn("sensitive", str(error.exception))
        self.assertNotIn("sensitive", "\n".join(logged.output))
        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    @staticmethod
    def _audit_result(value):
        if isinstance(value, BaseException):
            return patch(
                "organizacion.services.memberships.AuditoriaService.log_event",
                side_effect=value,
            )
        return patch(
            "organizacion.services.memberships.AuditoriaService.log_event",
            return_value=value,
        )

    def test_failure_after_domain_writes_rolls_back_everything(self):
        with self.assertRaises(OrganizationUnavailableError):
            with self.assertLogs("organizacion.services.memberships", level="ERROR"):
                with patch.object(EventoMembresia, "save", side_effect=DatabaseError("storage failure")):
                    change_membership(self.command())

        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_control_revision_write_failure_rolls_back_membership_and_history(self):
        created = self.create_membership()
        command = self.next_command(
            created,
            action=MembershipOperation.CHANGE_ROLE,
            target_role="SUPERVISOR",
        )

        with self.assertRaises(OrganizationUnavailableError):
            with self.assertLogs("organizacion.services.memberships", level="ERROR"):
                with patch.object(
                    ControlOrganizacionEmpresa,
                    "save",
                    side_effect=DatabaseError("control write failure"),
                ):
                    change_membership(command)

        member = MembresiaDepartamental.objects.get(pk=created.membership_id)
        self.assertEqual((member.rol, member.version), ("STAFF", 1))
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_history_requires_read_permission_and_is_company_scoped(self):
        first = self.create_membership()
        change_membership(self.next_command(
            first, action=MembershipOperation.SUSPEND
        ))

        history = get_membership_history(
            company_id=self.empresa.pk,
            actor_id=self.actor.pk,
            membership_id=first.membership_id,
        )
        self.assertEqual(len(history), 2)
        self.assertEqual([row.sequence for row in history], [1, 1])
        self.assertEqual(history[0].organization_revision, 2)
        self.assertEqual(history[1].organization_revision, 3)
        with self.assertRaises(MembershipPermissionDenied):
            get_membership_history(
                company_id=self.empresa.pk,
                actor_id=self.sin_permiso_lectura.pk,
                membership_id=first.membership_id,
            )
        with self.assertRaises(OrganizationNotFoundError):
            get_membership_history(
                company_id=self.empresa.pk,
                actor_id=self.actor.pk,
                membership_id=999999,
            )

    def test_history_projection_does_not_expose_command_fingerprint(self):
        result = self.create_membership()
        history = get_membership_history(
            company_id=self.empresa.pk,
            actor_id=self.actor.pk,
            membership_id=result.membership_id,
        )

        self.assertFalse(hasattr(history[0], "huella_solicitud"))
        self.assertEqual(history[0].expected_organization_revision, None)


class MembershipCommandTransactionTests(TransactionTestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="84", descripcion="Empresa transaccional")
        self.department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="TX",
            nombre="Departamento transaccional",
            source=OrganizationalSource.LOCAL,
        )
        self.actor = User.objects.create(
            username="t176-transaction-actor",
            password=make_password("test"),
        )
        self.user = User.objects.create(
            username="t176-transaction-user",
            password=make_password("test"),
        )
        profile = PerfilAcceso.objects.create(nombre="Perfil transaccional T176")
        for user in (self.actor, self.user):
            UsuarioPerfilEmpresa.objects.create(
                usuario=user,
                empresa=self.empresa,
                perfil=profile,
                asignado_por=self.actor,
            )
        vista = Vista.objects.create(nombre=MASTER_VIEW)
        Permiso.objects.create(
            usuario=self.actor,
            empresa=self.empresa,
            vista=vista,
            crear=True,
            modificar=True,
            eliminar=True,
            ingresar=True,
        )

    def command(self):
        return MembershipCommand(
            company_id=self.empresa.pk,
            actor_id=self.actor.pk,
            user_id=self.user.pk,
            department_id=self.department.pk,
            operation_id=uuid4(),
            action=MembershipOperation.CREATE,
            reason="Alta transaccional",
            target_role="STAFF",
            expected_membership_version=None,
            expected_organization_revision=None,
        )

    def test_successful_command_commits_all_four_records_on_default(self):
        result = change_membership(self.command())

        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        self.assertTrue(MembresiaDepartamental.objects.filter(pk=result.membership_id).exists())
        self.assertTrue(EventoMembresia.objects.filter(pk=result.event_id).exists())
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        records = (
            MembresiaDepartamental.objects.get(pk=result.membership_id),
            EventoMembresia.objects.get(pk=result.event_id),
            AuditoriaOrganizacionEvent.objects.get(),
        )
        self.assertEqual({record._state.db for record in records}, {"default"})

    def test_outer_rollback_reverts_all_four_records(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic(using="default"):
                change_membership(self.command())
                self.assertEqual(MembresiaDepartamental.objects.count(), 1)
                self.assertEqual(EventoMembresia.objects.count(), 1)
                self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
                raise RuntimeError("abort outer transaction")

        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())


class MembershipReplayMigrationTests(TransactionTestCase):
    previous = [("organizacion", "0002_department_memberships")]
    target = [("organizacion", "0003_eventomembresia_huella_solicitud_and_more")]

    def test_additive_migration_preserves_legacy_rows_with_nullable_replay_fields(self):
        executor = MigrationExecutor(connection)
        migration = executor.loader.get_migration(*self.target[0])
        self.assertEqual(
            executor.loader.graph.leaf_nodes("organizacion"),
            self.target,
        )
        self.assertEqual(len(migration.operations), 3)
        self.assertTrue(all(operation.__class__.__name__ == "AddField"
                            for operation in migration.operations))
        try:
            executor.migrate(self.previous)
            old_apps = executor.loader.project_state(self.previous).apps
            Company = old_apps.get_model("access_control", "Empresa")
            Department = old_apps.get_model("organizacion", "Departamento")
            Member = old_apps.get_model("organizacion", "MembresiaDepartamental")
            Event = old_apps.get_model("organizacion", "EventoMembresia")
            UserModel = old_apps.get_model("auth", "User")
            company = Company.objects.create(codigo="83", descripcion="Migración T176")
            department = Department.objects.create(
                empresa_id=company.pk,
                codigo="MIG",
                nombre="Migración",
                source="LOCAL",
            )
            user = UserModel.objects.create(
                username="t176-migration",
                password=make_password("test"),
            )
            member = Member.objects.create(
                empresa_id=company.pk,
                departamento_id=department.pk,
                usuario_id=user.pk,
                rol="STAFF",
                estado="ACTIVA",
                version=1,
            )
            event = Event.objects.create(
                membresia_id=member.pk,
                empresa_id=company.pk,
                usuario_afectado_id=user.pk,
                departamento_id=department.pk,
                autor_id=user.pk,
                operacion_id=uuid4(),
                secuencia=1,
                tipo="ALTA",
                motivo="Evento histórico",
                rol_despues="STAFF",
                estado_despues="ACTIVA",
                version_despues=1,
            )

            executor = MigrationExecutor(connection)
            executor.migrate(self.target)
            new_apps = MigrationExecutor(connection).loader.project_state(self.target).apps
            NewMember = new_apps.get_model("organizacion", "MembresiaDepartamental")
            NewEvent = new_apps.get_model("organizacion", "EventoMembresia")
            self.assertTrue(NewMember.objects.filter(pk=member.pk, version=1).exists())
            upgraded = NewEvent.objects.filter(pk=event.pk).values(
                "motivo",
                "huella_solicitud",
                "revision_organizacion_esperada",
                "revision_organizacion",
            ).get()
            self.assertEqual(upgraded["motivo"], "Evento histórico")
            self.assertIsNone(upgraded["huella_solicitud"])
            self.assertIsNone(upgraded["revision_organizacion_esperada"])
            self.assertIsNone(upgraded["revision_organizacion"])
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
