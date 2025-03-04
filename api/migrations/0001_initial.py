# Generated by Django 5.1.3 on 2024-12-12 01:02

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Contratopublicidad',
            fields=[
                ('rut_numero', models.CharField(max_length=20, primary_key=True, serialize=False)),
                ('rut', models.CharField(max_length=10)),
                ('numero', models.CharField(max_length=10)),
                ('fechainicio', models.DateField()),
                ('fechatermino', models.DateField()),
                ('facturar', models.CharField(max_length=1)),
                ('base', models.CharField(max_length=1)),
                ('monto', models.FloatField()),
                ('descontado', models.IntegerField()),
                ('rutcontacto', models.CharField(max_length=10)),
                ('nombrecontacto', models.CharField(max_length=50)),
                ('glosa', models.TextField()),
            ],
            options={
                'db_table': 'contratopublicidad',
                'managed': False,
            },
        ),
    ]
