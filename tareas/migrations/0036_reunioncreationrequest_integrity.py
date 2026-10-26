from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tareas", "0035_reunioncreationrequest"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="reunioncreationrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(payload_hash__regex=r"^[0-9a-f]{64}$"),
                name="tareas_rc_payload_hash_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="reunioncreationrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(review_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="tareas_rc_review_hash_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="reunioncreationrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    audit_status__in=[
                        "NOT_QUEUED",
                        "PENDING",
                        "CONFIRMED",
                        "ERROR",
                    ],
                ),
                name="tareas_rc_audit_status_ck",
            ),
        ),
    ]
