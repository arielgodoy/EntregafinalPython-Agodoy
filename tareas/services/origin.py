from django.core.exceptions import ValidationError

from tareas.models import Tarea, Todo, TodoEvento
from tareas.services.origin_storage import resolve_origin_storage


def create_task_from_todo(todo, usuario, titulo, descripcion="", comentario="", **kwargs):
    if not isinstance(todo, Todo):
        raise ValidationError("El origen debe ser un TO-DO válido.")
    if kwargs.get("empresa") is not None and kwargs["empresa"].id != todo.empresa_id:
        raise ValidationError("La Tarea debe pertenecer a la empresa del TO-DO.")
    if kwargs.get("tarea_origen") is not None or "todo_origen" in kwargs:
        raise ValidationError("Una Tarea originada desde TO-DO no puede tener otro origen canónico.")
    task = Tarea(
        titulo=titulo,
        descripcion=descripcion,
        empresa=todo.empresa,
        creada_por=usuario,
        todo_origen=todo,
        **{key: value for key, value in kwargs.items() if key != "empresa"},
    )
    storage = resolve_origin_storage()
    with storage.atomic() as unit:
        return unit.create_task_from_todo(task, usuario, comentario)