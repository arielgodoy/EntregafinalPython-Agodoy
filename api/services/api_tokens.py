import hashlib
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from api.models import ApiToken


TOKEN_PREFIX = "eltit_api"
PREFIX_BYTES = 9
SECRET_BYTES = 32


class InvalidApiToken(Exception):
    """Raised when an API token cannot be used."""


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_prefix():
    return secrets.token_urlsafe(PREFIX_BYTES)


def _generate_secret():
    return secrets.token_urlsafe(SECRET_BYTES)


def create_api_token(*, user, name, expires_at=None, created_by=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("El nombre del token es obligatorio.")
    if expires_at is not None and timezone.is_naive(expires_at):
        raise ValueError("expires_at debe ser timezone-aware.")

    for _ in range(10):
        prefix = _generate_prefix()
        secret = _generate_secret()
        token_value = f"{TOKEN_PREFIX}_{prefix}_{secret}"
        try:
            with transaction.atomic():
                api_token = ApiToken.objects.create(
                    user=user,
                    name=name,
                    prefix=prefix,
                    token_hash=_hash_token(token_value),
                    expires_at=expires_at,
                    created_by=created_by,
                )
            return api_token, token_value
        except IntegrityError:
            if ApiToken.objects.filter(prefix=prefix).exists():
                continue
            raise

    raise RuntimeError("No fue posible generar un prefijo único.")


def revoke_api_token(api_token):
    if api_token.revoked_at is None:
        api_token.revoked_at = timezone.now()
        api_token.is_active = False
        api_token.save(update_fields=["is_active", "revoked_at"])
    elif api_token.is_active:
        api_token.is_active = False
        api_token.save(update_fields=["is_active"])
    return api_token


def validate_api_token(token_value):
    if not isinstance(token_value, str) or not token_value:
        raise InvalidApiToken("Token API inválido.")

    token_hash = _hash_token(token_value)
    try:
        api_token = ApiToken.objects.select_related("user").get(token_hash=token_hash)
    except ApiToken.DoesNotExist as exc:
        raise InvalidApiToken("Token API inválido.") from exc

    if (
        not api_token.is_active
        or api_token.revoked_at is not None
        or api_token.is_expired
        or not api_token.user.is_active
    ):
        raise InvalidApiToken("Token API inválido.")

    return api_token
