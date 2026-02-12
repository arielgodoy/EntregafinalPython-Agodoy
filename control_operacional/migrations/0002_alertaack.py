from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('access_control', '0002_perfilacceso_perfilaccesodetalle_and_more'),
        ('control_operacional', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlertaAck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_key', models.CharField(max_length=200)),
                ('acknowledged_at', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alertas_ack', to='access_control.empresa')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alertas_ack', to='auth.user')),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('empresa', 'user', 'alert_key'), name='uniq_alerta_ack'),
                ],
            },
        ),
    ]
