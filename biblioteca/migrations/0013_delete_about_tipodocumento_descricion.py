# Generated by Django 4.2.4 on 2023-08-07 14:00

import ckeditor.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('biblioteca', '0012_about'),
    ]

    operations = [
        migrations.DeleteModel(
            name='About',
        ),
        migrations.AddField(
            model_name='tipodocumento',
            name='descricion',
            field=ckeditor.fields.RichTextField(default=''),
        ),
    ]
