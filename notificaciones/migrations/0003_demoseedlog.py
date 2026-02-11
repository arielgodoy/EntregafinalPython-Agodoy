from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0002_perfilacceso_perfilaccesodetalle_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("notificaciones", "0002_notification_dedupe_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemoSeedLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("payload_json", models.JSONField(default=dict)),
                (
                    "created_by_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="demo_seed_logs",
                        to="auth.user",
                    ),
                ),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demo_seed_logs",
                        to="access_control.empresa",
                    ),
                ),
            ],
        ),
    ]
