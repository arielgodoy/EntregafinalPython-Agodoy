from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from tareas.models import (
    Comentario,
    ComentarioPausaLectura,
    TareaLectura,
    TareaParticipante,
)
from tareas.services.assignment import add_participant, remove_participant
from tareas.services.reading import (
    close_inactivity_pause,
    count_pending_comments,
    get_first_pending_comment,
    get_initial_comment_page,
    get_previous_comment_page,
    open_inactivity_pause,
    recognize_loaded_comments,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class CommentReadingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="C099R", descripcion="Empresa Lectura")
        cls.lector = create_user(username="reading-user")
        cls.otro_lector = create_user(username="reading-other-user")
        cls.autor = create_user(username="reading-author")
        for user in (cls.lector, cls.otro_lector, cls.autor):
            assign_permission(user, cls.empresa, "Tareas", ingresar=True)
        cls.admin = create_user(username="reading-participants-admin")
        assign_permission(cls.admin, cls.empresa, "Tareas", ingresar=True, modificar=True)

    def make_task(self, *, lector=None):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.autor)
        add_participant(tarea, self.autor, actor=self.admin)
        add_participant(tarea, lector or self.lector, actor=self.admin)
        return tarea

    def make_comment(self, tarea, *, autor=None, created_at=None, oculto=False):
        comentario = Comentario.objects.create(
            tarea=tarea,
            autor=autor or self.autor,
            contenido="Comentario",
            oculto=oculto,
        )
        if created_at is not None:
            Comentario.objects.filter(pk=comentario.pk).update(created_at=created_at)
            comentario.refresh_from_db()
        return comentario

    def test_counter_and_first_pending_without_comments(self):
        tarea = self.make_task()

        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 0)
        self.assertIsNone(get_first_pending_comment(tarea=tarea, usuario=self.lector))

    def test_counter_excludes_own_and_includes_hidden(self):
        tarea = self.make_task()
        own = self.make_comment(tarea, autor=self.lector)
        hidden = self.make_comment(tarea, oculto=True)

        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 1)
        self.assertEqual(
            get_first_pending_comment(tarea=tarea, usuario=self.lector),
            hidden,
        )
        self.assertNotEqual(hidden, own)

    def test_counter_is_isolated_by_user_and_task(self):
        tarea = self.make_task()
        otra_tarea = self.make_task(lector=self.otro_lector)
        self.make_comment(tarea)
        self.make_comment(otra_tarea)

        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 1)
        with self.assertRaises(ValidationError):
            count_pending_comments(tarea=otra_tarea, usuario=self.lector)

    def test_pause_uses_half_open_boundaries(self):
        tarea = self.make_task()
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        start = timezone.now() - timedelta(minutes=2)
        end = start + timedelta(minutes=1)
        before = self.make_comment(tarea, created_at=start - timedelta(microseconds=1))
        self.make_comment(tarea, created_at=start)
        at_end = self.make_comment(tarea, created_at=end)
        ComentarioPausaLectura.objects.create(lectura=lectura, desde=start, hasta=end)

        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 2)
        self.assertEqual(get_first_pending_comment(tarea=tarea, usuario=self.lector), before)
        self.assertNotEqual(before, at_end)

    def test_initial_page_is_next_twenty_and_recognition_advances_only_to_its_end(self):
        tarea = self.make_task()
        comentarios = [self.make_comment(tarea) for _index in range(25)]

        pagina = get_initial_comment_page(tarea=tarea, usuario=self.lector)
        self.assertEqual([item.pk for item in pagina], [item.pk for item in comentarios[:20]])
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta)

        lectura = recognize_loaded_comments(
            tarea=tarea,
            usuario=self.lector,
            comentario_ids=[item.pk for item in pagina],
        )

        self.assertEqual(lectura.comentario_leido_hasta_id, comentarios[19].pk)
        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 5)

    def test_recognition_rejects_arbitrary_or_incomplete_page(self):
        tarea = self.make_task()
        comentarios = [self.make_comment(tarea) for _index in range(21)]

        with self.assertRaises(ValidationError):
            recognize_loaded_comments(
                tarea=tarea,
                usuario=self.lector,
                comentario_ids=[item.pk for item in comentarios[1:21]],
            )
        with self.assertRaises(ValidationError):
            recognize_loaded_comments(
                tarea=tarea,
                usuario=self.lector,
                comentario_ids=[item.pk for item in comentarios[:5]],
            )

        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta)

    def test_excluded_comments_inside_loaded_page_do_not_block_cursor(self):
        tarea = self.make_task()
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        first = self.make_comment(tarea)
        own = self.make_comment(tarea, autor=self.lector)
        paused = self.make_comment(tarea)
        ComentarioPausaLectura.objects.create(
            lectura=lectura,
            desde=paused.created_at,
            hasta=paused.created_at + timedelta(seconds=1),
        )

        lectura = recognize_loaded_comments(
            tarea=tarea,
            usuario=self.lector,
            comentario_ids=[first.pk, own.pk, paused.pk],
        )

        self.assertEqual(lectura.comentario_leido_hasta_id, paused.pk)
        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 0)

    def test_historical_page_does_not_move_cursor(self):
        tarea = self.make_task()
        comentarios = [self.make_comment(tarea) for _index in range(25)]
        recognize_loaded_comments(
            tarea=tarea,
            usuario=self.lector,
            comentario_ids=[item.pk for item in comentarios[:20]],
        )

        pagina = get_previous_comment_page(
            tarea=tarea,
            usuario=self.lector,
            before_comment=comentarios[19],
        )

        self.assertEqual([item.pk for item in pagina], [item.pk for item in comentarios[:19]])
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        self.assertEqual(lectura.comentario_leido_hasta_id, comentarios[19].pk)

    def test_without_pending_initial_page_returns_latest_twenty_in_chronological_order(self):
        tarea = self.make_task()
        comentarios = [self.make_comment(tarea, autor=self.lector) for _index in range(25)]

        pagina = get_initial_comment_page(tarea=tarea, usuario=self.lector)

        self.assertEqual([item.pk for item in pagina], [item.pk for item in comentarios[-20:]])

    def test_pause_open_and_close_are_idempotent_and_preserve_cursor(self):
        tarea = self.make_task()
        cursor = self.make_comment(tarea)
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        lectura.comentario_leido_hasta = cursor
        lectura.save(update_fields=["comentario_leido_hasta"])
        start = timezone.now()

        first = open_inactivity_pause(lectura=lectura, at=start)
        second = open_inactivity_pause(lectura=lectura, at=start + timedelta(seconds=1))
        self.assertEqual(
            ComentarioPausaLectura.objects.filter(lectura=lectura, hasta__isnull=True).count(),
            1,
        )
        closed = close_inactivity_pause(lectura=lectura, at=start + timedelta(seconds=2))
        repeated = close_inactivity_pause(lectura=lectura, at=start + timedelta(seconds=3))

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.pk, closed.pk)
        self.assertIsNone(repeated)
        self.assertEqual(
            ComentarioPausaLectura.objects.filter(lectura=lectura, hasta__isnull=True).count(),
            0,
        )
        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, cursor.pk)

    def test_saved_user_activity_transition_opens_and_closes_one_pause(self):
        tarea = self.make_task()
        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)

        self.lector.is_active = False
        self.lector.save(update_fields=["is_active"])
        self.lector.save(update_fields=["is_active"])

        pausa = ComentarioPausaLectura.objects.get(lectura=lectura)
        self.assertIsNone(pausa.hasta)

        self.lector.is_active = True
        self.lector.save(update_fields=["is_active"])

        pausa.refresh_from_db()
        self.assertIsNotNone(pausa.hasta)
        self.assertGreaterEqual(pausa.hasta, pausa.desde)

    def test_inactivity_preserves_previous_pending_and_excludes_pause_comments(self):
        tarea = self.make_task()
        previous = self.make_comment(tarea)
        self.lector.is_active = False
        self.lector.save(update_fields=["is_active"])
        during = self.make_comment(tarea)
        self.lector.is_active = True
        self.lector.save(update_fields=["is_active"])
        after = self.make_comment(tarea)

        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 2)
        self.assertEqual(get_first_pending_comment(tarea=tarea, usuario=self.lector), previous)
        self.assertNotEqual(previous, during)
        self.assertNotEqual(during, after)

    def test_first_comment_event_creates_single_reader_for_existing_participant(self):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.autor)
        TareaParticipante.objects.create(tarea=tarea, usuario=self.lector)

        comentario = self.make_comment(tarea)

        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta)
        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 1)
        self.assertEqual(TareaLectura.objects.filter(tarea=tarea, usuario=self.lector).count(), 1)
        self.assertEqual(get_first_pending_comment(tarea=tarea, usuario=self.lector), comentario)

    def test_relink_keeps_zero_historical_pending(self):
        tarea = self.make_task()
        self.make_comment(tarea)
        remove_participant(tarea, self.lector, actor=self.admin)
        newest = self.make_comment(tarea)

        add_participant(tarea, self.lector, actor=self.admin)

        lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
        self.assertEqual(lectura.comentario_leido_hasta_id, newest.pk)
        self.assertEqual(count_pending_comments(tarea=tarea, usuario=self.lector), 0)