from django.core.exceptions import ValidationError
from django.utils import timezone

from tareas.models import Tarea, Todo
from tareas.services.todo_storage import resolve_todo_storage


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
    todo = Todo(
        empresa=empresa,
        creada_por=usuario,
        titulo=titulo,
        descripcion=descripcion,
        todo_anterior=todo_anterior,
    )
    return resolve_todo_storage().create_todo(todo, usuario)


def _has_pending_originated_tasks(todo, storage):
    if todo.pk is None:
        raise ValueError("The TO-DO must be saved before checking originated tasks.")
    for task_id, state in storage.get_originated_tasks(todo.pk):
        if state == Tarea.Estado.CERRADA:
            continue
        if any(storage.get_task_annulment_chain(task_id)):
            continue
        return True
    return False


def close_todo(todo, usuario, comentario=""):
    _validate_same_company(todo, usuario)
    storage = resolve_todo_storage()
    if todo.pk:
        todo.estado = storage.get_todo_state(todo.pk)
    if todo.estado == Todo.Estado.CERRADO:
        raise ValidationError("El TO-DO ya está cerrado y no puede reabrirse.")
    if _has_pending_originated_tasks(todo, storage):
        raise ValidationError("No se puede cerrar un TO-DO con Tareas originadas pendientes.")
    todo.estado = Todo.Estado.CERRADO
    todo.cerrada_por = usuario
    todo.fecha_cierre = timezone.now()
    todo.comentario_cierre = comentario
    with storage.atomic() as unit:
        unit.save_closed_todo(todo, usuario)
    return todo