from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('access_control', '0002_perfilacceso_perfilaccesodetalle_and_more'),
        ('chat', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversacion',
            name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='conversaciones', to='access_control.empresa'),
        ),
    ]
