from django.db import models
from decimal import Decimal
from datetime import datetime, date

from .models import AuditoriaBibliotecaEvent


class AuditoriaService:
    """
    Servicio centralizado para logging de auditoría.
    Decide en qué tabla escribir según app_label.
    """

    APP_MODEL_MAP = {
        'biblioteca': AuditoriaBibliotecaEvent,
    }

    @classmethod
    def diff_snapshots(cls, before, after):
        """
        Calcula diferencias entre snapshots dict.
        Retorna dict: {campo: {'from': old, 'to': new}}

        - before None + after dict => todos los campos son nuevos (from=None)
        - after None + before dict => todos los campos eliminados (to=None)
        - ambos dict => comparar normal
        - ambos None => {}
        """
        if before is None and after is None:
            return {}

        before = before or {}
        after = after or {}

        changes = {}
        keys = set(before.keys()) | set(after.keys())

        for k in keys:
            old = before.get(k, None)
            new = after.get(k, None)
            if old != new:
                changes[k] = {'from': old, 'to': new}

        return changes

    @classmethod
    def log_event(cls, app_label, **event_data):
        """
        Registra un evento de auditoría en la tabla correspondiente.
        """
        model_class = cls.APP_MODEL_MAP.get(app_label)
        if not model_class:
            return None

        event_data = cls._sanitize_data(event_data)
        return model_class.objects.create(**event_data)

    @classmethod
    def _sanitize_data(cls, data):
        """
        Elimina datos sensibles de meta, before, after.
        """
        sensitive_keys = ['password', 'token', 'secret', 'api_key', 'csrfmiddlewaretoken']

        for field in ['meta', 'before', 'after']:
            if field in data and isinstance(data[field], dict):
                data[field] = {
                    k: v for k, v in data[field].items()
                    if k.lower() not in sensitive_keys
                }

        return data

    @classmethod
    def model_to_snapshot(cls, obj, max_string_length=1000):
        """
        Serializa un objeto Django Model a dict sanitizado para auditoría.
        """
        if obj is None:
            return None

        snapshot = {}
        sensitive_keys = ['password', 'token', 'secret', 'api_key', 'csrf']

        for field in obj._meta.get_fields():
            field_name = getattr(field, 'name', None)
            if not field_name:
                continue

            if any(sensitive in field_name.lower() for sensitive in sensitive_keys):
                continue

            if getattr(field, 'auto_created', False) or getattr(field, 'many_to_many', False):
                continue

            try:
                value = getattr(obj, field_name, None)

                if isinstance(field, models.FileField):
                    snapshot[field_name] = value.name if value else None

                elif isinstance(field, models.ForeignKey):
                    snapshot[field_name + '_id'] = value.pk if value else None

                elif isinstance(value, (datetime, date)):
                    snapshot[field_name] = value.isoformat()

                elif isinstance(value, Decimal):
                    snapshot[field_name] = str(value)

                elif isinstance(value, str) and len(value) > max_string_length:
                    snapshot[field_name] = value[:max_string_length] + '...[truncado]'

                else:
                    snapshot[field_name] = value

            except Exception:
                continue

        return snapshot
