from django.core.exceptions import ValidationError
from django.db import transaction

from tareas.models import Tarea, Todo, TodoEvento


def create_task_from_todo(todo, usuario, titulo, descripcion="", comentario="", **kwargs):
    if not isinstance(todo, Todo):
        raise ValidationError("El origen debe ser un TO-DO válido.")
    if kwargs.get("empresa") is not None and kwargs["empresa"].id != todo.empresa_id:
        raise ValidationError("La Tarea debe pertenecer a la empresa del TO-DO.")
    if kwargs.get("tarea_origen") is not None or "todo_origen" in kwargs:
        raise ValidationError("Una Tarea originada desde TO-DO no puede tener otro origen canónico.")
    with transaction.atomic():
        task = Tarea.objects.create(
            titulo=titulo,
            descripcion=descripcion,
            empresa=todo.empresa,
            creada_por=usuario,
            todo_origen=todo,
            **{key: value for key, value in kwargs.items() if key != "empresa"},
        )
        TodoEvento.objects.create(
            todo=todo,
            tipo=TodoEvento.Tipo.TAREA_CREADA,
            usuario=usuario,
            comentario=comentario,
            tarea=task,
        )
    return task