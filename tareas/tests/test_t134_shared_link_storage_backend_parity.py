from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from tareas.models import EnlaceTarea, EventoAccesoEnlace, Tarea
from tareas.services import shared_link_storage as storage
from tareas.services.connection_roles import TareaConnectionError


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []
        self.lastrowid = 71

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class DjangoSharedLinkStorageTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="SLD", descripcion="Django links")
        self.user = User.objects.create_user("shared_link_django")
        perfil = PerfilAcceso.objects.create(nombre="Shared link Django")
        UsuarioPerfilEmpresa.objects.create(usuario=self.user, empresa=self.empresa, perfil=perfil)
        self.task = Tarea.objects.create(
            titulo="Django backend task",
            correlativo="SLD-0001",
            empresa=self.empresa,
            creada_por=self.user,
        )
        self.command = storage.SharedLinkCreateCommand(
            task_id=self.task.pk,
            empresa_id=self.empresa.pk,
            destinatario_id=self.user.pk,
            creado_por_id=self.user.pk,
            fecha_expiracion=timezone.now() + timedelta(days=1),
            token="django-token",
            token_hash=storage.hash_link_token("django-token"),
        )

    def test_create_and_resolve_use_explicit_alias(self):
        backend = storage.DjangoSharedLinkStorage("default")
        created = backend.create(self.command)
        resolved = backend.resolve("django-token", self.user.pk, self.empresa.pk)

        self.assertEqual(created.tarea.pk, self.task.pk)
        self.assertEqual(resolved.task.pk, self.task.pk)
        self.assertEqual(
            EventoAccesoEnlace.objects.using("default").filter(enlace_id=created.id).count(),
            1,
        )
        self.assertTrue(EnlaceTarea.objects.using("default").filter(pk=created.id).exists())


class MySQLSharedLinkStorageTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="SLM", descripcion="MySQL links")
        self.user = User.objects.create_user("shared_link_mysql")
        perfil = PerfilAcceso.objects.create(nombre="Shared link MySQL")
        UsuarioPerfilEmpresa.objects.create(usuario=self.user, empresa=self.empresa, perfil=perfil)
        self.connection_config = object()

    def test_create_resolve_and_revoke_use_configured_connection(self):
        create_cursor = FakeCursor([
            (17, "MySQL backend task", "description", "SLM-0001", "BORRADOR", "NORMAL", None, self.empresa.pk),
        ])
        create_connection = FakeConnection(create_cursor)
        backend = storage.MySQLSharedLinkStorage(self.connection_config, "configured_tasks")

        with patch.object(backend, "_validate_users"), patch(
            "tareas.services.shared_link_storage.open_mysql_connection",
            return_value=nullcontext(create_connection),
        ):
            created = backend.create(storage.SharedLinkCreateCommand(
                task_id=17,
                empresa_id=self.empresa.pk,
                destinatario_id=self.user.pk,
                creado_por_id=self.user.pk,
                fecha_expiracion=timezone.now() + timedelta(days=1),
                token="mysql-token",
                token_hash=storage.hash_link_token("mysql-token"),
            ))

        self.assertEqual(created.tarea.titulo, "MySQL backend task")
        self.assertEqual(create_connection.commits, 1)
        self.assertTrue(any("tareas_enlacetarea" in sql for sql, _ in create_cursor.executed))

        resolve_cursor = FakeCursor([
            (71, 17, self.user.pk, timezone.now() + timezone.timedelta(days=1), None,
             "MySQL backend task", "description", "SLM-0001", "BORRADOR", "NORMAL", None, self.empresa.pk),
        ])
        resolve_connection = FakeConnection(resolve_cursor)
        with patch(
            "tareas.services.shared_link_storage.open_mysql_connection",
            return_value=nullcontext(resolve_connection),
        ):
            resolved = backend.resolve("mysql-token", self.user.pk, self.empresa.pk)

        self.assertEqual(resolved.task.titulo, "MySQL backend task")
        self.assertEqual(resolved.task.pk, 17)
        self.assertEqual(resolve_connection.commits, 1)

        revoke_cursor = FakeCursor([(71, None)])
        revoke_connection = FakeConnection(revoke_cursor)
        with patch(
            "tareas.services.shared_link_storage.open_mysql_connection",
            return_value=nullcontext(revoke_connection),
        ):
            backend.revoke(storage.SharedLinkRevokeCommand(71, self.empresa.pk, self.user.pk))

        self.assertEqual(revoke_connection.commits, 1)
        self.assertTrue(any("UPDATE tareas_enlacetarea" in sql for sql, _ in revoke_cursor.executed))

    def test_same_pk_uses_mysql_task_data(self):
        cursor = FakeCursor([
            (17, "BASE_TAREAS title", "BASE_TAREAS description", "SLM-0001", "ACTIVA", "URGENTE", None, self.empresa.pk),
        ])
        connection = FakeConnection(cursor)
        backend = storage.MySQLSharedLinkStorage(self.connection_config, "configured_tasks")
        command = storage.SharedLinkCreateCommand(
            task_id=17,
            empresa_id=self.empresa.pk,
            destinatario_id=self.user.pk,
            creado_por_id=self.user.pk,
            fecha_expiracion=timezone.now() + timedelta(days=1),
            token="same-pk-token",
            token_hash=storage.hash_link_token("same-pk-token"),
        )
        with patch.object(backend, "_validate_users"), patch(
            "tareas.services.shared_link_storage.open_mysql_connection",
            return_value=nullcontext(connection),
        ):
            result = backend.create(command)

        self.assertEqual(result.task_id, 17)
        self.assertEqual(result.tarea.titulo, "BASE_TAREAS title")


class SharedLinkStorageResolutionTests(TestCase):
    def test_missing_base_tareas_role_fails_closed(self):
        with patch(
            "tareas.services.shared_link_storage.resolve_operational_backend",
            side_effect=TareaConnectionError("missing role"),
        ):
            with self.assertRaises(TareaConnectionError):
                storage.resolve_shared_link_storage()

    def test_invalid_backend_fails_closed(self):
        with patch(
            "tareas.services.shared_link_storage.resolve_operational_backend",
            return_value=type("Context", (), {"backend_type": "UNKNOWN"})(),
        ):
            with self.assertRaises(storage.TaskStorageError):
                storage.resolve_shared_link_storage()
