from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('gestiondte', '0003_cesionrpetc_tarearpetc_tareacesionrpetc_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='LecturaAutomaticaConfig',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('habilitado', models.BooleanField(default=False)),
                ('intervalo_minutos', models.PositiveSmallIntegerField(choices=[(15, '15 minutos'), (30, '30 minutos'), (60, '1 hora')], default=60)),
                ('ultima_ejecucion', models.DateTimeField(blank=True, null=True)),
                ('proxima_ejecucion', models.DateTimeField(blank=True, null=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('modificado', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='LecturaAutomaticaEjecucion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lote_id', models.UUIDField(db_index=True, default=uuid.uuid4)),
                ('tipo_ejecucion', models.CharField(choices=[('MANUAL', 'Manual'), ('AUTOMATICA', 'Automática')], max_length=12)),
                ('fecha_desde', models.DateField()),
                ('fecha_hasta', models.DateField()),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('EN_PROCESO', 'En proceso'), ('ACTUALIZADO', 'Actualizado'), ('ERROR', 'Error')], db_index=True, default='PENDIENTE', max_length=15)),
                ('progreso', models.PositiveSmallIntegerField(default=0)),
                ('total_documentos', models.PositiveIntegerField(blank=True, null=True)),
                ('documentos_procesados', models.PositiveIntegerField(default=0)),
                ('fecha_inicio', models.DateTimeField(blank=True, null=True)),
                ('fecha_termino', models.DateTimeField(blank=True, null=True)),
                ('ultima_actualizacion', models.DateTimeField(auto_now=True)),
                ('mensaje_error', models.TextField(blank=True, null=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lecturas_automaticas', to='access_control.empresa')),
                ('tarea_rpetc', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lecturas_automaticas', to='gestiondte.tarearpetc')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['lote_id', 'estado'], name='lectura_auto_lote_estado_idx'),
                    models.Index(fields=['empresa', 'estado'], name='lectura_auto_emp_estado_idx'),
                ],
            },
        ),
    ]
