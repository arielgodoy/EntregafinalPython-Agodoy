import logging

from django.db import migrations


logger = logging.getLogger(__name__)
IDENTITY_FIELDS = ("first_name", "last_name", "email")


def merge_missing_identity(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Avatar = apps.get_model("acounts", "Avatar")
    User = apps.get_model("auth", "User")
    copied = {field: 0 for field in IDENTITY_FIELDS}
    conflicts = {field: 0 for field in IDENTITY_FIELDS}

    for avatar in Avatar.objects.using(db_alias).select_related("user").all():
        user = avatar.user
        if user is None:
            continue

        fields_to_update = []
        for field in IDENTITY_FIELDS:
            user_value = (getattr(user, field, "") or "").strip()
            avatar_value = (getattr(avatar, field, "") or "").strip()
            if not user_value and avatar_value:
                setattr(user, field, avatar_value)
                fields_to_update.append(field)
                copied[field] += 1
            elif user_value and avatar_value and user_value != avatar_value:
                conflicts[field] += 1

        if fields_to_update:
            user.save(using=db_alias, update_fields=fields_to_update)

    logger.warning(
        "Avatar identity consolidation: copied_missing=%s conflicts=%s",
        copied,
        conflicts,
    )

    conflicts_total = sum(conflicts.values())
    if conflicts_total:
        raise RuntimeError(
            f"Se detectaron {conflicts_total} conflictos de identidad User/Avatar. "
            "La migración se detuvo antes de eliminar las columnas. "
            "Revise los conflictos antes de continuar."
        )


class Migration(migrations.Migration):

    atomic = True

    dependencies = [
        ("acounts", "0007_rename_acounts_use_user_id_65a30d_idx_acounts_use_user_id_02038b_idx"),
    ]

    operations = [
        migrations.RunPython(merge_missing_identity, migrations.RunPython.noop),
    ]
