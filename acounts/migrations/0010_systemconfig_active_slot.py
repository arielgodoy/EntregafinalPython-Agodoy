from django.db import migrations, models


def remove_legacy_active_constraint(apps, schema_editor):
    system_config = apps.get_model('acounts', 'SystemConfig')
    table_name = system_config._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            table_name,
        )
    if 'unique_active_system_config' not in constraints:
        return

    index_name = schema_editor.quote_name('unique_active_system_config')
    table = schema_editor.quote_name(table_name)
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.execute(f'DROP INDEX IF EXISTS {index_name}')
    else:
        schema_editor.execute(f'DROP INDEX {index_name} ON {table}')


def populate_active_slot(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    system_config = apps.get_model('acounts', 'SystemConfig')
    active_configs = system_config.objects.using(db_alias).filter(
        is_active=True,
    ).order_by('pk')

    first_active = True
    for config in active_configs.iterator():
        if first_active:
            config.active_slot = 'SYSTEM_CONFIG_ACTIVE'
            config.save(using=db_alias, update_fields=['active_slot'])
            first_active = False
        else:
            config.is_active = False
            config.active_slot = None
            config.save(using=db_alias, update_fields=['is_active', 'active_slot'])


class Migration(migrations.Migration):
    dependencies = [
        ('acounts', '0009_remove_avatar_email_remove_avatar_first_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemconfig',
            name='active_slot',
            field=models.CharField(blank=True, editable=False, max_length=32, null=True, unique=True),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(remove_legacy_active_constraint, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='systemconfig',
                    name='unique_active_system_config',
                ),
            ],
        ),
        migrations.RunPython(populate_active_slot, migrations.RunPython.noop),
    ]