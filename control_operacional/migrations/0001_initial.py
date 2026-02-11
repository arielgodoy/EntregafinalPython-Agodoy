from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('access_control', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegistroOperacional',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titulo', models.CharField(max_length=150)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registros_operacionales', to='access_control.empresa')),
            ],
            options={
                'verbose_name': 'Registro Operacional',
                'verbose_name_plural': 'Registros Operacionales',
                'ordering': ['-creado_en'],
            },
        ),
    ]
