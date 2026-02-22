from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0008_add_group_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversacion',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name='conversacion',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
