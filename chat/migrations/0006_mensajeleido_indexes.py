from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_mensajeleido"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="mensajeleido",
            index=models.Index(fields=["user", "mensaje"], name="chat_mensaj_user_id_4b5d6d_idx"),
        ),
        migrations.AddIndex(
            model_name="mensajeleido",
            index=models.Index(fields=["empresa", "user"], name="chat_mensaj_emprea_76b5a6_idx"),
        ),
    ]
