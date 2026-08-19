import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet():
    key = getattr(settings, 'PFX_FERNET_KEY', None)
    if key:
        if isinstance(key, str):
            key = key.encode()
        # Expecting a urlsafe base64-encoded key; if raw bytes provided, try to normalize
        try:
            # Ensure valid 32-byte base64 key
            base64.urlsafe_b64decode(key)
            k = key
        except Exception:
            k = base64.urlsafe_b64encode(key.ljust(32, b"\0")[:32])
    else:
        # Fallback for development: derive key from SECRET_KEY (NOT recommended for production)
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        k = base64.urlsafe_b64encode(digest)
    return Fernet(k)


def encrypt_password(password: str) -> bytes:
    if password is None:
        return None
    f = _get_fernet()
    return f.encrypt(password.encode())


def decrypt_password(token: bytes) -> str | None:
    if not token:
        return None
    f = _get_fernet()
    try:
        return f.decrypt(token).decode()
    except InvalidToken:
        return None
