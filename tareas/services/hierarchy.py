"""Hierarchy services for Phase 3 T028.

The hierarchy is limited to parent -> child -> grandchild. Annulment propagation
is logical only: child rows are never written when an ancestor is annulled.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from tareas.models import Tarea, TareaRelacion


def get_parent(task):
    relation = TareaRelacion.objects.filter(hija=task).select_related("padre").first()
    return relation.padre if relation else None


def get_children(task):
    return Tarea.objects.filter(relaciones_padre__padre=task).order_by("id")


def get_descendants(task):
    children = list(get_children(task))
    grandchildren = []
    for child in children:
        grandchildren.extend(list(get_children(child)))
    return children + grandchildren


def get_depth(task):
    depth = 0
    current = task
    seen = {task.pk}
    while True:
        parent = get_parent(current)
        if parent is None:
            return depth
        if parent.pk in seen:
            raise ValidationError("La jerarquía contiene un ciclo.")
        seen.add(parent.pk)
        depth += 1
        current = parent


def _would_create_cycle(parent, child):
    current = parent
    seen = set()
    while current is not None:
        if current.pk == child.pk:
            return True
        if current.pk in seen:
            return True
        seen.add(current.pk)
        current = get_parent(current)
    return False


def validate_relation(parent, child):
    if parent.pk is None or child.pk is None:
        raise ValidationError("Padre e hija deben existir antes de relacionarse.")
    if parent.pk == child.pk:
        raise ValidationError("Una tarea no puede ser hija de sí misma.")
    if parent.empresa_id != child.empresa_id:
        raise ValidationError("Padre e hija deben pertenecer a la misma empresa.")
    if get_parent(child) is not None:
        raise ValidationError("La tarea hija ya tiene un padre.")
    if get_depth(parent) >= 2:
        raise ValidationError("No se permite crear un nivel adicional bajo una nieta.")
    if _would_create_cycle(parent, child):
        raise ValidationError("La relación genera un ciclo jerárquico.")


def add_child(parent, child):
    validate_relation(parent, child)
    with transaction.atomic():
        return TareaRelacion.objects.create(padre=parent, hija=child)


def is_effectively_annulled(task):
    if task.anulada:
        return True
    parent = get_parent(task)
    if parent is None:
        return False
    if parent.anulada:
        return True
    grandparent = get_parent(parent)
    return bool(grandparent and grandparent.anulada)


def has_open_operational_descendants(task):
    for descendant in get_descendants(task):
        if descendant.estado == Tarea.Estado.CERRADA:
            continue
        if is_effectively_annulled(descendant):
            continue
        return True
    return False