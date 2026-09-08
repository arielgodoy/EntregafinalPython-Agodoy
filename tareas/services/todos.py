from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tareas.models import Tarea, Todo, TodoEvento
from tareas.services.hierarchy import is_effectively_annulled


def _validate_same_company(todo, user):
    if todo.empresa_id is None:
        raise ValidationError("El TO-DO requiere empresa.")
    return user


def create_todo(empresa, usuario, titulo, descripcion="", todo_anterior=None):
    if todo_anterior is not None:
        if todo_anterior.empresa_id != empresa.id:
            raise ValidationError("El episodio anterior debe pertenecer a la misma empresa.")
        if todo_anterior.estado != Todo.Estado.CERRADO:
            raise ValidationError("El episodio anterior debe estar cerrado.")
    with transaction.atomic():
        todo = Todo.objects.create(
            empresa=empresa,
            creada_por=usuario,
            titulo=titulo,
            descripcion=descripcion,
            todo_anterior=todo_anterior,
        )
        TodoEvento.objects.create(todo=todo, tipo=TodoEvento.Tipo.CREADO, usuario=usuario)
    return todo


def _has_pending_originated_tasks(todo):
    for task in todo.tareas_origen.select_related("empresa"):
        if task.estado == Tarea.Estado.CERRADA or is_effectively_annulled(task):
            continue
        return True
    return False


def close_todo(todo, usuario, comentario=""):
    _validate_same_company(todo, usuario)
    if todo.pk:
        todo.refresh_from_db(fields=["estado"])
    if todo.estado == Todo.Estado.CERRADO:
        raise ValidationError("El TO-DO ya está cerrado y no puede reabrirse.")
    if _has_pending_originated_tasks(todo):
        raise ValidationError("No se puede cerrar un TO-DO con Tareas originadas pendientes.")
    with transaction.atomic():
        todo.estado = Todo.Estado.CERRADO
        todo.cerrada_por = usuario
        todo.fecha_cierre = timezone.now()
        todo.comentario_cierre = comentario
        todo.save(update_fields=["estado", "cerrada_por", "fecha_cierre", "comentario_cierre"])
        TodoEvento.objects.create(
            todo=todo,
            tipo=TodoEvento.Tipo.CERRADO,
            usuario=usuario,
            comentario=comentario,
        )
    return todo