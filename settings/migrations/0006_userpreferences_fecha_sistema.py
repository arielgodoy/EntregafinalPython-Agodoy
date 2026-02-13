from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0005_theme_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreferences",
            name="fecha_sistema",
            field=models.DateField(blank=True, null=True),
        ),
    ]
