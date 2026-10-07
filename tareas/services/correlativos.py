"""Atomic task correlation number allocation for one company."""

from django.db import IntegrityError, transaction

from tareas.models import CorrelativoEmpresa, CorrelativoTodoEmpresa


def reserve_next_number(empresa_id, *, using=None):
    """Reserve one number for a company; publishing never calls this function."""
    manager = CorrelativoEmpresa.objects.using(using) if using else CorrelativoEmpresa.objects
    atomic_kwargs = {"using": using} if using else {}
    with transaction.atomic(**atomic_kwargs):
        try:
            sequence = manager.select_for_update().get(
                empresa_id=empresa_id
            )
        except CorrelativoEmpresa.DoesNotExist:
            try:
                with transaction.atomic(**atomic_kwargs):
                    sequence = manager.create(
                        empresa_id=empresa_id,
                        siguiente_numero=1,
                    )
            except IntegrityError:
                sequence = manager.select_for_update().get(
                    empresa_id=empresa_id
                )
        number = sequence.siguiente_numero
        sequence.siguiente_numero = number + 1
        sequence.save(using=using, update_fields=["siguiente_numero"])
        return number


def reserve_next_todo_number(empresa_id, *, using=None):
    """Reserve a TD number without sharing the Tarea sequence."""
    manager = CorrelativoTodoEmpresa.objects.using(using) if using else CorrelativoTodoEmpresa.objects
    atomic_kwargs = {"using": using} if using else {}
    with transaction.atomic(**atomic_kwargs):
        try:
            sequence = manager.select_for_update().get(
                empresa_id=empresa_id
            )
        except CorrelativoTodoEmpresa.DoesNotExist:
            try:
                with transaction.atomic(**atomic_kwargs):
                    sequence = manager.create(
                        empresa_id=empresa_id,
                        siguiente_numero=1,
                    )
            except IntegrityError:
                sequence = manager.select_for_update().get(
                    empresa_id=empresa_id
                )
        number = sequence.siguiente_numero
        sequence.siguiente_numero = number + 1
        sequence.save(using=using, update_fields=["siguiente_numero"])
        return number
