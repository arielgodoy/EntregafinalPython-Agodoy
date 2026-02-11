from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notificaciones", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="dedupe_key",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["dedupe_key", "destinatario"], name="notif_dedupe_dest_idx"),
        ),
    ]
