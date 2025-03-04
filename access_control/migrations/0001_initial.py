# Generated by Django 5.1.3 on 2024-12-03 00:06

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Empresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=2, unique=True, validators=[django.core.validators.RegexValidator(message='El código debe ser un número de 2 dígitos entre 00 y 99.', regex='^\\d{2}$')], verbose_name='Código')),
                ('descripcion', models.TextField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Vista',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=255)),
                ('descripcion', models.TextField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Permiso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ingresar', models.BooleanField(default=False)),
                ('crear', models.BooleanField(default=False)),
                ('modificar', models.BooleanField(default=False)),
                ('eliminar', models.BooleanField(default=False)),
                ('autorizar', models.BooleanField(default=False)),
                ('supervisor', models.BooleanField(default=False)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='access_control.empresa')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('vista', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='access_control.vista')),
            ],
            options={
                'unique_together': {('usuario', 'empresa', 'vista')},
            },
        ),
    ]
