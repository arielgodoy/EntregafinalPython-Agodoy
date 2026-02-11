from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0003_populate_conversacion_empresa'),
        ('access_control', '0002_perfilacceso_perfilaccesodetalle_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversacion',
            name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conversaciones', to='access_control.empresa'),
        ),
    ]
