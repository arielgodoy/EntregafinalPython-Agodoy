from gestiondte.models import GestionDTEConnectionRole


def configure_serverbasedte_django():
    role, _ = GestionDTEConnectionRole.objects.get_or_create(
        role='serverbasedte',
        defaults={'source_type': 'DJANGO', 'django_alias': 'default'},
    )
    if role.source_type != 'DJANGO' or role.django_alias != 'default':
        role.source_type = 'DJANGO'
        role.django_alias = 'default'
        role.mysql_connection = None
        role.database_name = None
        role.save(update_fields=['source_type', 'django_alias', 'mysql_connection', 'database_name', 'updated_at'])
    return role
