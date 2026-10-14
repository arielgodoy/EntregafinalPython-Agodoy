"""Record Persona's operational schema state without issuing database DDL."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evaluaciones", "0007_remove_evaluacionconnectionrole_eval_conn_role_source_chk_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="persona",
                    name="person_id",
                    field=models.IntegerField(),
                ),
                migrations.AlterField(
                    model_name="persona",
                    name="rut",
                    field=models.CharField(blank=True, max_length=20, null=True),
                ),
                migrations.AlterField(
                    model_name="persona",
                    name="mes",
                    field=models.PositiveSmallIntegerField(),
                ),
                migrations.AlterField(
                    model_name="persona",
                    name="anio",
                    field=models.PositiveSmallIntegerField(),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="buk_employee_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="fecha_corte",
                    field=models.DateField(),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="rut_normalizado",
                    field=models.CharField(max_length=20),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="active_until",
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="company_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="role_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="role_code",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="role_name",
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="role_family_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="role_family_name",
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="area_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="cost_center",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="recinto_asistencia_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="recinto_asistencia_code",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="recinto_primario_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="recinto_primario_code",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="ctrlit_recinto",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="job_id",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="job_start_date",
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="job_end_date",
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="contract_type",
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name="persona",
                    name="buk_payload",
                    field=models.JSONField(),
                ),
                migrations.AddConstraint(
                    model_name="persona",
                    constraint=models.UniqueConstraint(
                        fields=("anio", "mes", "rut_normalizado"),
                        name="eval_person_month_rut_uq",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="persona",
                    constraint=models.CheckConstraint(
                        condition=models.Q(mes__gte=1, mes__lte=12),
                        name="eval_person_month_chk",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="persona",
                    constraint=models.CheckConstraint(
                        condition=models.Q(anio__gte=1),
                        name="eval_person_year_chk",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="persona",
                    constraint=models.CheckConstraint(
                        condition=models.Q(rut_normalizado__gt=""),
                        name="eval_person_rut_nonempty_chk",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=[
                            "anio",
                            "mes",
                            "company_id",
                            "recinto_asistencia_code",
                            "role_id",
                        ],
                        name="eval_person_period_org_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=["person_id"],
                        name="eval_person_buk_person_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=["buk_employee_id"],
                        name="eval_person_buk_emp_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=["company_id"],
                        name="eval_person_company_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=["recinto_asistencia_code"],
                        name="eval_person_recinto_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="persona",
                    index=models.Index(
                        fields=["role_id"],
                        name="eval_person_role_idx",
                    ),
                ),
            ],
        ),
    ]
