from django.core.management.base import BaseCommand

from notificaciones.models import Notification


class Command(BaseCommand):
    help = "Clean access request notification bodies by removing raw grant URLs."

    def handle(self, *args, **options):
        qs = Notification.objects.filter(
            tipo=Notification.Tipo.SYSTEM,
            titulo="Solicitud de acceso",
            cuerpo__icontains="http",
        )
        updated = 0
        for notification in qs:
            cuerpo = notification.cuerpo or ""
            marker = "Otorgar acceso:"
            if marker in cuerpo:
                cuerpo = cuerpo.split(marker)[0].rstrip()
            else:
                cuerpo = cuerpo.split("http")[0].rstrip()
            if cuerpo != notification.cuerpo:
                notification.cuerpo = cuerpo
                notification.save(update_fields=["cuerpo"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} notifications."))
