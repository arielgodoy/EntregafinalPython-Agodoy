from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from tareas.models import Comentario
from tareas.services.reading import (
    ensure_readings_for_comment,
    handle_user_activity_transition,
)


User = get_user_model()


@receiver(pre_save, sender=User, dispatch_uid="tareas_capture_user_activity")
def capture_user_activity(sender, instance, raw=False, update_fields=None, **kwargs):
    instance._tareas_previous_is_active = None
    if raw or instance._state.adding:
        return
    if update_fields is not None and "is_active" not in update_fields:
        return
    instance._tareas_previous_is_active = (
        sender.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()
    )


@receiver(post_save, sender=User, dispatch_uid="tareas_observe_user_activity")
def observe_user_activity(sender, instance, raw=False, **kwargs):
    previous = getattr(instance, "_tareas_previous_is_active", None)
    if hasattr(instance, "_tareas_previous_is_active"):
        del instance._tareas_previous_is_active
    if raw or previous is None or previous == instance.is_active:
        return
    handle_user_activity_transition(usuario=instance, was_active=previous)


@receiver(post_save, sender=Comentario, dispatch_uid="tareas_ensure_comment_readings")
def ensure_comment_readings(sender, instance, created=False, raw=False, **kwargs):
    if created and not raw:
        ensure_readings_for_comment(comentario=instance)