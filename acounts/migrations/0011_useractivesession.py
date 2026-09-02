from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('acounts', '0010_systemconfig_active_slot'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserActiveSession',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('session_key', models.CharField(max_length=40, unique=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'user',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='active_session',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
