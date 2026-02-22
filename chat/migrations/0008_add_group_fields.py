from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0007_rename_chat_mensaj_user_id_4b5d6d_idx_chat_mensaj_user_id_019acb_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversacion',
            name='is_group',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='conversacion',
            name='nombre',
            field=models.CharField(max_length=200, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='conversacion',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='conversacion',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
