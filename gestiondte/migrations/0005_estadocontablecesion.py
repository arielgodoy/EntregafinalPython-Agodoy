from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('gestiondte', '0004_lectura_automatica'),
    ]

    operations = [
        migrations.CreateModel(
            name='EstadoContableCesion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estado_contabilizacion', models.CharField(choices=[('CONTABILIZADA', 'Contabilizada'), ('NO_CONTABILIZADA', 'No contabilizada'), ('REVISAR', 'Revisar'), ('NO_DISPONIBLE', 'No disponible')], max_length=20)),
                ('estado_factoring', models.CharField(choices=[('PAGADA', 'Pagada'), ('NO_PAGADA', 'No pagada'), ('REVISAR', 'Revisar'), ('NO_DISPONIBLE', 'No disponible')], max_length=20)),
                ('estado_proveedor', models.CharField(choices=[('PAGADA', 'Pagada'), ('NO_PAGADA', 'No pagada'), ('REVISAR', 'Revisar'), ('NO_DISPONIBLE', 'No disponible')], max_length=20)),
                ('estado_pago_resumen', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('PAGADA_FACTORING', 'Pagada a factoring'), ('PAGADA_PROVEEDOR', 'Pagada a proveedor'), ('PAGADA_AMBOS', 'Pagada a factoring y proveedor'), ('REVISAR', 'Revisar'), ('NO_DISPONIBLE', 'No disponible')], max_length=20)),
                ('fecha_pago_factoring', models.DateTimeField(blank=True, null=True)),
                ('monto_pago_factoring', models.DecimalField(blank=True, decimal_places=0, max_digits=20, null=True)),
                ('fecha_pago_proveedor', models.DateTimeField(blank=True, null=True)),
                ('monto_pago_proveedor', models.DecimalField(blank=True, decimal_places=0, max_digits=20, null=True)),
                ('fecha_verificacion', models.DateTimeField(default=django.utils.timezone.now)),
                ('estado_verificacion', models.CharField(choices=[('OK', 'Correcta'), ('ERROR', 'Error')], default='OK', max_length=5)),
                ('mensaje_error', models.CharField(blank=True, max_length=500, null=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('modificado', models.DateTimeField(auto_now=True)),
                ('cesion', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='estados_contables', to='gestiondte.cesionrpetc')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='estados_contables_cesiones', to='access_control.empresa')),
            ],
        ),
        migrations.AddIndex(
            model_name='estadocontablecesion',
            index=models.Index(fields=['empresa', 'estado_pago_resumen'], name='rpetc_estado_emp_pago_idx'),
        ),
        migrations.AddIndex(
            model_name='estadocontablecesion',
            index=models.Index(fields=['empresa', 'fecha_verificacion'], name='rpetc_estado_emp_verif_idx'),
        ),
        migrations.AddConstraint(
            model_name='estadocontablecesion',
            constraint=models.UniqueConstraint(fields=('empresa', 'cesion'), name='rpetc_estado_empresa_cesion_unico'),
        ),
    ]
