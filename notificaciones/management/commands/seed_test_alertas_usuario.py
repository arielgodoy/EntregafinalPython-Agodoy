from datetime import timedelta
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from notificaciones.models import Notification


class Command(BaseCommand):
    help = "Seed controlled notifications for a specific user and company."

    def add_arguments(self, parser):
        parser.add_argument("--empresa_codigo", type=str, required=True)
        parser.add_argument("--username", type=str, required=True)
        parser.add_argument("--cantidad", type=int, default=6)
        parser.add_argument("--force-membership", action="store_true", default=False)

    def handle(self, *args, **options):
        empresa_codigo = options.get("empresa_codigo")
        username = options.get("username")
        cantidad = int(options.get("cantidad") or 0)
        if cantidad < 0:
            cantidad = 0

        try:
            empresa = Empresa.objects.get(codigo=empresa_codigo)
        except Empresa.DoesNotExist:
            self.stdout.write(f"Empresa no encontrada para codigo: {empresa_codigo}")
            sys.exit(1)

        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(username=username)
        except UserModel.DoesNotExist:
            self.stdout.write(f"Usuario no encontrado: {username}")
            sys.exit(1)

        has_assignment = UsuarioPerfilEmpresa.objects.filter(usuario=user, empresa=empresa).exists()
        if not has_assignment:
            if not options.get("force_membership"):
                self.stdout.write("ERROR: usuario no pertenece a la empresa indicada. Usa --force-membership para DEV.")
                sys.exit(1)

            perfil = PerfilAcceso.objects.order_by("id").first()
            if not perfil:
                self.stdout.write("ERROR: no hay PerfilAcceso disponible para crear membership.")
                sys.exit(1)

            UsuarioPerfilEmpresa.objects.get_or_create(
                usuario=user,
                empresa=empresa,
                defaults={
                    "perfil": perfil,
                    "asignado_por": None,
                },
            )
            self.stdout.write(
                f"Membership creado: {user.username} -> empresa {empresa.codigo} (empresa_id={empresa.id})"
            )

        tipos = ["MESSAGE", "ALERT", "SYSTEM"]
        offset_map = {
            "MESSAGE": 0,
            "ALERT": 100,
            "SYSTEM": 200,
        }
        created_total = 0
        created_counts = {tipo: 0 for tipo in tipos}

        for tipo in tipos:
            for i in range(1, cantidad + 1):
                notification = Notification.objects.create(
                    empresa=empresa,
                    destinatario=user,
                    actor=None,
                    tipo=tipo,
                    titulo=f"[DEMO {tipo}] Notificacion {i}",
                    cuerpo=f"Notificacion de prueba tipo {tipo} numero {i} para validar UI topbar.",
                    url="/notificaciones/mis-notificaciones/",
                    dedupe_key="",
                    is_read=False,
                )
                created_at = timezone.now() - timedelta(minutes=(i + offset_map[tipo]))
                Notification.objects.filter(id=notification.id).update(created_at=created_at)
                created_total += 1
                created_counts[tipo] += 1

        empresa_nombre = empresa.descripcion or ""
        self.stdout.write(f"Empresa usada: {empresa.codigo} - {empresa_nombre} (empresa_id={empresa.id})")
        self.stdout.write(f"Usuario usado: {user.username} (user_id={user.id})")
        self.stdout.write(f"Cantidad por tipo: {cantidad}")
        self.stdout.write(f"Total creadas: {created_total}")
        self.stdout.write(f"MESSAGE: {created_counts['MESSAGE']}")
        self.stdout.write(f"ALERT: {created_counts['ALERT']}")
        self.stdout.write(f"SYSTEM: {created_counts['SYSTEM']}")
