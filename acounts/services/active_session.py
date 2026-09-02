"""Control server-side de la unica sesion activa por usuario."""
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.db import transaction

from acounts.models import UserActiveSession


def register_active_session(user, new_session_key):
    """Registra la nueva sesion y elimina la anterior bajo lock por usuario."""
    if not new_session_key:
        raise ValueError("La sesion activa debe tener una session_key")

    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        active_session, _ = UserActiveSession.objects.select_for_update().get_or_create(
            user=locked_user,
            defaults={"session_key": new_session_key},
        )
        old_session_key = active_session.session_key
        if old_session_key != new_session_key:
            Session.objects.filter(session_key=old_session_key).delete()
            active_session.session_key = new_session_key
            active_session.save(update_fields=["session_key", "updated_at"])


def clear_active_session(user, current_session_key):
    """Limpia solo la asociacion que todavia pertenece a la sesion indicada."""
    if not current_session_key:
        return

    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        UserActiveSession.objects.filter(
            user=locked_user,
            session_key=current_session_key,
        ).delete()
