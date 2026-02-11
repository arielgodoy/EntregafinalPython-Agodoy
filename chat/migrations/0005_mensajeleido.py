from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0002_perfilacceso_perfilaccesodetalle_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("chat", "0004_conversacion_empresa_non_null"),
    ]

    operations = [
        migrations.CreateModel(
            name="MensajeLeido",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mensajes_leidos",
                        to="access_control.empresa",
                    ),
                ),
                (
                    "mensaje",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leidos",
                        to="chat.mensaje",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mensajes_leidos",
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=["mensaje", "user"], name="uniq_mensaje_user_leido"),
                ],
            },
        ),
    ]
