# Generated migration file for control_de_proyectos

from django.db import migrations, models
import django.db.models.deletion
import control_de_proyectos.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('access_control', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClienteEmpresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=150)),
                ('rut', models.CharField(help_text='Formato: XX.XXX.XXX-X', max_length=20, unique=True, validators=[control_de_proyectos.models.validar_rut])),
                ('telefono', models.CharField(blank=True, max_length=20)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('direccion', models.TextField(blank=True)),
                ('ciudad', models.CharField(blank=True, max_length=100)),
                ('contacto_nombre', models.CharField(blank=True, max_length=100)),
                ('contacto_telefono', models.CharField(blank=True, max_length=20)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Cliente Empresa',
                'verbose_name_plural': 'Clientes Empresas',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='EspecialidadProfesional',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Especialidad Profesional',
                'verbose_name_plural': 'Especialidades Profesionales',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='TipoProyecto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Tipo de Proyecto',
                'verbose_name_plural': 'Tipos de Proyectos',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='Profesional',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=150)),
                ('rut', models.CharField(help_text='Formato: XX.XXX.XXX-X', max_length=20, unique=True, validators=[control_de_proyectos.models.validar_rut])),
                ('email', models.EmailField(max_length=254)),
                ('telefono', models.CharField(blank=True, max_length=20)),
                ('especialidad_texto', models.CharField(help_text='Especialidad (se normaliza automáticamente)', max_length=100)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('especialidad_ref', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='profesionales', to='control_de_proyectos.especialidadprofesional')),
                ('user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='profesional_profile', to='auth.user')),
            ],
            options={
                'verbose_name': 'Profesional',
                'verbose_name_plural': 'Profesionales',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='Proyecto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200)),
                ('descripcion', models.TextField(blank=True)),
                ('tipo_texto', models.CharField(help_text='Tipo de proyecto (se normaliza automáticamente)', max_length=100)),
                ('estado', models.CharField(choices=[('FUTURO_ESTUDIO', 'Futuro Estudio'), ('EN_ESTUDIO', 'En Estudio'), ('EN_COTIZACION', 'En Cotización'), ('EN_EJECUCION', 'En Ejecución'), ('TERMINADO', 'Terminado')], default='FUTURO_ESTUDIO', max_length=20)),
                ('fecha_inicio_estimada', models.DateField(blank=True, null=True)),
                ('fecha_termino_estimada', models.DateField(blank=True, null=True)),
                ('fecha_inicio_real', models.DateField(blank=True, null=True)),
                ('fecha_termino_real', models.DateField(blank=True, null=True)),
                ('presupuesto', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('monto_facturado', models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=12, null=True)),
                ('observaciones', models.TextField(blank=True)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proyectos', to='control_de_proyectos.clienteempresa')),
                ('empresa_interna', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proyectos', to='access_control.empresa')),
                ('profesionales', models.ManyToManyField(blank=True, related_name='proyectos', to='control_de_proyectos.profesional')),
                ('tipo_ref', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='proyectos', to='control_de_proyectos.tipoproyecto')),
            ],
            options={
                'verbose_name': 'Proyecto',
                'verbose_name_plural': 'Proyectos',
                'ordering': ['-fecha_creacion'],
                'unique_together': {('nombre', 'empresa_interna', 'cliente')},
            },
        ),
        migrations.CreateModel(
            name='Tarea',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200)),
                ('descripcion', models.TextField(blank=True)),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('EN_PROGRESO', 'En Progreso'), ('COMPLETADA', 'Completada'), ('CANCELADA', 'Cancelada')], default='PENDIENTE', max_length=20)),
                ('prioridad', models.CharField(choices=[('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta'), ('URGENTE', 'Urgente')], default='MEDIA', max_length=20)),
                ('fecha_inicio', models.DateField(blank=True, null=True)),
                ('fecha_termino_estimada', models.DateField(blank=True, null=True)),
                ('fecha_termino_real', models.DateField(blank=True, null=True)),
                ('horas_estimadas', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('horas_reales', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('profesional_asignado', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tareas_asignadas', to='control_de_proyectos.profesional')),
                ('proyecto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tareas', to='control_de_proyectos.proyecto')),
            ],
            options={
                'verbose_name': 'Tarea',
                'verbose_name_plural': 'Tareas',
                'ordering': ['proyecto', '-prioridad', '-fecha_creacion'],
            },
        ),
    ]
