from datetime import date
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from tareas.models import (
    Comentario,
    ComentarioVersion,
    Tarea,
    TareaConnectionRole,
)
from tareas.services.comment_storage import (
    CommentCreateCommand,
    CommentEditCommand,
    CommentPageCommand,
    MySQLCommentStorage,
    RecognizeCommentsCommand,
    ReadingCommand,
    resolve_comment_storage,
    TaskDTO,
)
from tareas.services.comments import create_comment
from tareas.services.participants import is_effective_participant
from tareas.services.task_storage import TaskStorageError


class CommentsReadingBackendParityTests(TestCase):
    databases = {"default", "system_test"}

    @classmethod
    def setUpTestData(cls):
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default",
        )
        cls.default_empresa = Empresa.objects.create(
            codigo="CRA", descripcion="Default A",
        )
        cls.default_user = User.objects.create_user("comment_parity")
        perfil = PerfilAcceso.objects.create(nombre="Comments parity")
        UsuarioPerfilEmpresa.objects.create(
            usuario=cls.default_user, empresa=cls.default_empresa, perfil=perfil,
        )
        vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.default_user, empresa=cls.default_empresa, vista=vista,
            ingresar=True, crear=True, modificar=True, supervisor=True,
        )
        cls.default_task = Tarea.objects.create(
            titulo="Task A",
            correlativo="B0000001",
            empresa=cls.default_empresa,
            creada_por=cls.default_user,
            responsable=cls.default_user,
            fecha_tope=date.today(),
            estado=Tarea.Estado.ACTIVA,
        )
        cls.default_comment = Comentario.objects.create(
            pk=1,
            tarea=cls.default_task,
            autor=cls.default_user,
            contenido="Comentario A",
        )
        Empresa.objects.using("system_test").create(
            pk=cls.default_empresa.pk, codigo="CRB", descripcion="BASE_TAREAS B",
        )
        User.objects.using("system_test").bulk_create([
            User(pk=cls.default_user.pk, username="comment_parity"),
        ])
        Tarea.objects.using("system_test").create(
            pk=cls.default_task.pk,
            titulo="Task B",
            correlativo="B0000001",
            empresa_id=cls.default_empresa.pk,
            creada_por_id=cls.default_user.pk,
            responsable_id=cls.default_user.pk,
            fecha_tope=date.today(),
            estado=Tarea.Estado.ACTIVA,
        )
        Comentario.objects.using("system_test").create(
            pk=cls.default_comment.pk,
            tarea_id=cls.default_task.pk,
            autor_id=cls.default_user.pk,
            contenido="Comentario B",
        )

    def setUp(self):
        self.role.django_alias = "default"
        self.role.save(update_fields=["django_alias"])

    def test_django_alias_same_pk_create_edit_version_and_reading(self):
        self.role.django_alias = "system_test"
        self.role.save(update_fields=["django_alias"])
        storage = resolve_comment_storage()

        current = storage.get(1, self.default_task.pk, self.default_empresa.pk)
        self.assertEqual(current.contenido, "Comentario B")
        edited = storage.edit(CommentEditCommand(
            comment_id=1,
            task_id=self.default_task.pk,
            empresa_id=self.default_empresa.pk,
            actor_id=self.default_user.pk,
            content="Comentario B editado",
        ))
        self.assertEqual(edited.contenido, "Comentario B editado")
        self.assertTrue(ComentarioVersion.objects.using("system_test").filter(
            comentario_id=1, evento=ComentarioVersion.Evento.EDITADO,
        ).exists())
        self.assertEqual(
            Comentario.objects.using("default").get(pk=1).contenido,
            "Comentario A",
        )

        reading = storage.reading(ReadingCommand(
            self.default_task.pk, self.default_empresa.pk, self.default_user.pk,
        ))
        recognized = storage.recognize(RecognizeCommentsCommand(
            self.default_task.pk, self.default_empresa.pk, self.default_user.pk, (1,),
        ))
        self.assertEqual(recognized.comentario_leido_hasta_id, 1)
        self.assertEqual(reading.tarea_id, self.default_task.pk)

    def test_django_alias_create_and_visibility(self):
        self.role.django_alias = "system_test"
        self.role.save(update_fields=["django_alias"])
        storage = resolve_comment_storage()
        created = storage.create(CommentCreateCommand(
            task_id=self.default_task.pk,
            empresa_id=self.default_empresa.pk,
            author_id=self.default_user.pk,
            content="Nuevo B",
        ))
        self.assertEqual(created.contenido, "Nuevo B")
        hidden = storage.set_visibility(__import__(
            "tareas.services.comment_storage", fromlist=["CommentVisibilityCommand"]
        ).CommentVisibilityCommand(
            created.pk, self.default_task.pk, self.default_empresa.pk,
            self.default_user.pk, "motivo", True,
        ))
        self.assertTrue(hidden.oculto)
        self.assertFalse(Comentario.objects.using("default").filter(contenido="Nuevo B").exists())

    def test_invalid_backend_fails_closed(self):
        with patch(
            "tareas.services.comment_storage.resolve_operational_backend",
            side_effect=RuntimeError("missing backend"),
        ):
            with self.assertRaises(RuntimeError):
                resolve_comment_storage()

    def test_mysql_task_dto_preserves_priority(self):
        class Cursor:
            description = ()

            def execute(self, sql, params=()):
                pass

            def fetchone(self):
                return (7, self.default_empresa_id, "GESTION", "URGENTE", 0, 11, 12)

            def fetchall(self):
                return [(13,)]

            def close(self):
                pass

        class Connection:
            def __init__(self, empresa_id):
                self.cursor_value = Cursor()
                self.cursor_value.default_empresa_id = empresa_id

            def cursor(self):
                return self.cursor_value

        storage = MySQLCommentStorage(object(), "configured_tasks")
        with patch(
            "tareas.services.comment_storage.open_mysql_connection",
            return_value=nullcontext(Connection(self.default_empresa.pk)),
        ):
            task = storage.task(7, self.default_empresa.pk)

        self.assertEqual(task.prioridad, "URGENTE")
        self.assertEqual(task._tareas_effective_user_ids, {11, 12, 13})

    def test_mysql_task_dto_participant_parity_is_fail_closed(self):
        task = TaskDTO(
            id=7,
            empresa_id=self.default_empresa.pk,
            estado="GESTION",
            prioridad="NORMAL",
            anulada=False,
            creador_id=11,
            responsable_id=12,
            empresa=self.default_empresa,
            explicit_participant_ids=(13,),
        )

        self.assertTrue(is_effective_participant(task, SimpleNamespace(pk=11)))
        self.assertTrue(is_effective_participant(task, SimpleNamespace(pk=12)))
        self.assertTrue(is_effective_participant(task, SimpleNamespace(pk=13)))
        self.assertFalse(is_effective_participant(task, SimpleNamespace(pk=14)))

    def test_mysql_comment_service_allows_explicit_participant_only(self):
        participant = self.default_user
        non_participant = User.objects.create_user("comment-parity-outsider")
        task = TaskDTO(
            id=7,
            empresa_id=self.default_empresa.pk,
            estado="GESTION",
            prioridad="NORMAL",
            anulada=False,
            creador_id=11,
            responsable_id=12,
            empresa=self.default_empresa,
            explicit_participant_ids=(participant.pk,),
        )
        storage = type("Storage", (), {
            "task": lambda _self, task_id, empresa_id: task,
            "create": lambda _self, command, **kwargs: SimpleNamespace(
                contenido=command.content,
            ),
        })()
        with patch("tareas.services.comments.resolve_comment_storage", return_value=storage), \
             patch("tareas.services.comments.is_effectively_annulled", return_value=False), \
             patch("tareas.services.comments.user_has_permission_for_empresa", return_value=True), \
             patch("tareas.services.comments._schedule_comment_event"):
            created = create_comment(
                tarea=task,
                usuario=participant,
                contenido="Participante explícito",
            )
            with self.assertRaises(ValidationError):
                create_comment(
                    tarea=task,
                    usuario=non_participant,
                    contenido="No permitido",
                )

        self.assertEqual(created.contenido, "Participante explícito")

    def test_notification_is_after_storage_commit(self):
        events = []
        storage = resolve_comment_storage()
        original_create = storage.create

        def mark_commit(command, **kwargs):
            events.append("commit")
            return original_create(command, **kwargs)

        with patch("tareas.services.comments.resolve_comment_storage") as resolve, \
             patch("tareas.services.comments.emit_task_event", side_effect=lambda **kwargs: events.append("notification")):
            resolve.return_value = storage
            with patch.object(storage, "create", side_effect=mark_commit):
                with self.captureOnCommitCallbacks(execute=True):
                    create_comment(tarea=self.default_task, usuario=self.default_user, contenido="ordered")

        self.assertEqual(events, ["commit", "notification"])

    def test_failed_storage_does_not_notify(self):
        with patch("tareas.services.comments.resolve_comment_storage") as resolve, \
             patch("tareas.services.comments.emit_task_event") as notify:
            resolve.return_value = type("FailingStorage", (), {
                "task": lambda _self, task_id, empresa_id: self.default_task,
                "create": lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rollback")),
            })()
            with self.assertRaises(RuntimeError):
                create_comment(tarea=self.default_task, usuario=self.default_user, contenido="failed")
        notify.assert_not_called()

    def test_notification_failure_does_not_remove_committed_comment(self):
        with patch("tareas.services.comments.emit_task_event", side_effect=RuntimeError("notify")):
            with self.captureOnCommitCallbacks(execute=True):
                create_comment(tarea=self.default_task, usuario=self.default_user, contenido="committed")
        self.assertTrue(Comentario.objects.filter(contenido="committed").exists())

    def test_django_activity_opens_and_closes_pause(self):
        self.role.django_alias = "system_test"
        self.role.save(update_fields=["django_alias"])
        storage = resolve_comment_storage()
        reading = storage.reading(ReadingCommand(
            self.default_task.pk, self.default_empresa.pk, self.default_user.pk,
        ))
        opened = storage.open_pause(ReadingCommand(
            self.default_task.pk, self.default_empresa.pk, self.default_user.pk,
        ))
        closed = storage.close_pause(ReadingCommand(
            self.default_task.pk, self.default_empresa.pk, self.default_user.pk,
        ))
        self.assertEqual(opened.lectura_id, reading.pk)
        self.assertIsNotNone(closed.hasta)

    def test_mysql_activity_opens_and_closes_pause(self):
        class Cursor:
            def __init__(self, reading_rows, pause_rows):
                self.reading_rows = list(reading_rows)
                self.rows = list(pause_rows)
                self.sql = []
                self.lastrowid = 9

            def execute(self, sql, params=()):
                self.sql.append(sql)

            def fetchone(self):
                return self.rows.pop(0) if self.rows else None

            def fetchall(self):
                rows, self.reading_rows = self.reading_rows, []
                return rows

            def close(self):
                pass

        class Connection:
            def __init__(self, cursor):
                self.cursor_value = cursor

            def cursor(self):
                return self.cursor_value

            def commit(self):
                pass

            def rollback(self):
                pass

        inactive = Cursor([(5,)], [None])
        active = Cursor([(5,)], [(9, object())])
        storage = MySQLCommentStorage(object(), "configured_tasks")
        with patch(
            "tareas.services.comment_storage.open_mysql_connection",
            side_effect=[nullcontext(Connection(inactive)), nullcontext(Connection(active))],
        ):
            storage.handle_user_activity(self.default_user.pk, False, timezone.now())
            storage.handle_user_activity(self.default_user.pk, True, timezone.now())
        self.assertTrue(any("INSERT INTO tareas_comentariopausalectura" in sql for sql in inactive.sql))
        self.assertTrue(any("UPDATE tareas_comentariopausalectura" in sql for sql in active.sql))
