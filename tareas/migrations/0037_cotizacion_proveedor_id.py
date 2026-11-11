from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tareas", "0036_reunioncreationrequest_integrity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="cotizacion",
                    name="proveedor",
                ),
                migrations.AddField(
                    model_name="cotizacion",
                    name="proveedor_id",
                    field=models.BigIntegerField(
                        blank=True,
                        db_index=True,
                        null=True,
                    ),
                ),
            ],
        ),
    ]
