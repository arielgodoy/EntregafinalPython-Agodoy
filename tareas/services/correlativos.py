"""Atomic task correlation number allocation for one company."""

from django.db import IntegrityError, transaction

from tareas.models import CorrelativoEmpresa


def reserve_next_number(empresa_id):
    """Reserve one number for a company; publishing never calls this function."""
    with transaction.atomic():
        try:
            sequence = CorrelativoEmpresa.objects.select_for_update().get(
                empresa_id=empresa_id
            )
        except CorrelativoEmpresa.DoesNotExist:
            try:
                with transaction.atomic():
                    sequence = CorrelativoEmpresa.objects.create(
                        empresa_id=empresa_id,
                        siguiente_numero=1,
                    )
            except IntegrityError:
                sequence = CorrelativoEmpresa.objects.select_for_update().get(
                    empresa_id=empresa_id
                )
        number = sequence.siguiente_numero
        sequence.siguiente_numero = number + 1
        sequence.save(update_fields=["siguiente_numero"])
        return number
