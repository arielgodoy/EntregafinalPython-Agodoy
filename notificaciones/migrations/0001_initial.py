from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("access_control", "0002_perfilacceso_perfilaccesodetalle_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo", models.CharField(choices=[("SYSTEM", "SYSTEM"), ("ALERT", "ALERT"), ("MESSAGE", "MESSAGE")], max_length=20)),
                ("titulo", models.CharField(max_length=255)),
                ("cuerpo", models.TextField(blank=True)),
                ("url", models.CharField(blank=True, max_length=500)),
                ("is_read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notificaciones_emitidas", to=settings.AUTH_USER_MODEL)),
                ("destinatario", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notificaciones_recibidas", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="access_control.empresa")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["destinatario", "is_read"], name="notif_dest_isread_idx"),
                    models.Index(fields=["empresa", "destinatario", "created_at"], name="notif_emp_dest_created_idx"),
                ],
            },
        ),
    ]
