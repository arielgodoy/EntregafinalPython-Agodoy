from django.core.management.base import BaseCommand

from access_control.services.view_catalog import ensure_protected_views_catalog


class Command(BaseCommand):
    help = "Registra las Vistas protegidas de URLs activas sin crear permisos."

    def handle(self, *args, **options):
        summary = ensure_protected_views_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                "Catálogo protegido: "
                f"creadas {summary.created}, existentes {summary.existing}, "
                f"rutas actualizadas {summary.route_names_updated}, "
                f"incidencias {summary.invalid_count}."
            )
        )
        for issue in summary.issues:
            self.stdout.write(
                self.style.WARNING(
                    f"{issue.issue}: {issue.view_name} ({issue.route_name or 'sin ruta'})"
                )
            )