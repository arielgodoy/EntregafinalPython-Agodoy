from django.core.management.base import BaseCommand, CommandError

from tareas.services.master_catalog_common import MasterCatalogError
from tareas.services.master_operation_service import reconcile_master_operations
from tareas.services.master_operation_store import MasterOperationError


class Command(BaseCommand):
    help = (
        "Reconcile a bounded batch of committed events and report uncertain "
        "master-catalog operations without replaying them."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        try:
            report = reconcile_master_operations(limit=options["limit"])
        except (MasterCatalogError, MasterOperationError) as exc:
            raise CommandError(
                "No se pudo completar la reconciliación de auditoría de maestros."
            ) from exc

        summary = (
            f"scanned={report.scanned} attempted={report.attempted} "
            f"confirmed={report.confirmed} retryable={report.retryable_errors} "
            f"permanent={report.permanent_errors} "
            f"unknown={report.unknown_operations} "
            f"pending={report.pending_operations}"
        )
        self.stdout.write(summary)
        for review in report.manual_review:
            self.stdout.write(
            "manual_review "
            f"operation_id={review.operation_id} "
            f"entity={review.entity_type} "
            f"empresa_id={review.empresa_id} "
            f"status={review.status} "
            f"audit_status={review.audit_status} "
            f"evidence={review.evidence} "
            f"reason={review.reason}"
            )
        if (
            report.retryable_errors
            or report.permanent_errors
            or report.unknown_operations
            or report.pending_operations
        ):
            raise CommandError(
                "Hay operaciones pendientes o inciertas; revise el resumen y "
                "repita solo las operaciones reintentables."
            )
