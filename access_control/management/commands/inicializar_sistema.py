import getpass

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from access_control.services.system_bootstrap import (
    BootstrapInconsistency,
    initialize_system_for_user,
)


class Command(BaseCommand):
    help = "Inicializa Empresa 00, vistas base y un superusuario administrativo."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--dry-run", action="store_true", help="Muestra cambios sin escribir la base de datos.")

    def handle(self, *args, **options):
        username = options["username"]
        dry_run = options["dry_run"]
        user_data = {}
        existing_user = User.objects.filter(username=username).first()
        if not dry_run and existing_user is None:
            user_data = {
                "email": input("Email: "),
                "first_name": input("Nombre: "),
                "last_name": input("Apellido: "),
                "password": getpass.getpass("Password: "),
            }
            confirmation = getpass.getpass("Password confirmation: ")
            if user_data["password"] != confirmation:
                raise CommandError("Las contraseñas no coinciden.")

        try:
            summary = initialize_system_for_user(
                username=username,
                dry_run=dry_run,
                **user_data,
            )
        except (BootstrapInconsistency, ValidationError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: no se realizaron cambios en la base de datos."))
        else:
            self.stdout.write(self.style.SUCCESS("INICIALIZACIÓN COMPLETADA"))
        self.stdout.write(f"Empresa 00: {'creada' if summary.empresa_created else 'reutilizada'}")
        self.stdout.write(f"Vistas Control de Acceso: {summary.access_views_count}")
        self.stdout.write(f"Vistas SYSTEM adicionales: {summary.system_views_count}")
        self.stdout.write(f"Total Vistas bootstrap: {summary.views_processed}")
        if dry_run:
            self.stdout.write("Incluidas: " + ", ".join(summary.bootstrap_view_names))
        self.stdout.write(f"Excluidas APPLICATION: {summary.application_views_excluded}")
        self.stdout.write(f"Ambiguas/omitidas: {summary.ambiguous_views_count}")
        if summary.application_view_names:
            self.stdout.write("APPLICATION: " + ", ".join(summary.application_view_names))
        if summary.ambiguous_view_names:
            self.stdout.write("Ambiguas: " + ", ".join(summary.ambiguous_view_names))
        self.stdout.write(
            f"Usuario {username}: {'creado' if summary.user_created else 'reutilizado'}; "
            "superuser: sí; staff: sí"
        )
        self.stdout.write(
            f"Vistas: procesadas {summary.views_processed}, creadas {summary.views_created}, "
            f"existentes {summary.views_existing}"
        )
        self.stdout.write(
            f"Permisos: procesados {summary.permissions_processed}, creados {summary.permissions_created}, "
            f"actualizados {summary.permissions_updated}, sin cambios {summary.permissions_unchanged}"
        )
        if not dry_run:
            self.stdout.write("Sistema listo para iniciar sesión.")