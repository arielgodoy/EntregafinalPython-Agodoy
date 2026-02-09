import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from acounts.models import SystemConfig, UserEmailToken, UserEmailTokenPurpose
from acounts.services.config import get_effective_company_config


DEFAULT_TTL_HOURS = 24


def _hash_token(token_plain: str) -> str:
    return hashlib.sha256(token_plain.encode('utf-8')).hexdigest()


def _resolve_empresa_from_meta(meta):
    if not meta:
        return None
    empresa = meta.get('empresa')
    if empresa is not None:
        return empresa
    empresa_id = meta.get('empresa_id')
    return empresa_id


def _get_activation_ttl_seconds(meta):
    empresa_or_id = _resolve_empresa_from_meta(meta)
    if empresa_or_id is not None:
        config = get_effective_company_config(empresa_or_id)
        ttl_hours = config.get('activation_ttl_hours') if config else None
    else:
        system_config = SystemConfig.objects.filter(is_active=True).first()
        ttl_hours = system_config.activation_ttl_hours if system_config else None

    ttl_hours = ttl_hours or DEFAULT_TTL_HOURS
    return int(ttl_hours * 3600)


def generate_token(user, purpose=UserEmailTokenPurpose.ACTIVATE, ttl_seconds=None, created_by=None, meta=None):
    token_plain = secrets.token_urlsafe(32)
    token_hash = _hash_token(token_plain)
    ttl = ttl_seconds if ttl_seconds is not None else _get_activation_ttl_seconds(meta)
    expires_at = timezone.now() + timedelta(seconds=ttl)

    UserEmailToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by=created_by,
        meta=meta,
    )

    return token_plain


def validate_and_use_token(token_plain, purpose=UserEmailTokenPurpose.ACTIVATE):
    token_hash = _hash_token(token_plain)
    now = timezone.now()

    with transaction.atomic():
        updated = UserEmailToken.objects.filter(
            token_hash=token_hash,
            purpose=purpose,
            used_at__isnull=True,
            expires_at__gt=now,
        ).update(used_at=now)

        if updated == 0:
            return None

        token_obj = UserEmailToken.objects.filter(token_hash=token_hash).first()
        return token_obj.user if token_obj else None
