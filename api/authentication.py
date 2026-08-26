from dataclasses import dataclass

from api.services.api_tokens import InvalidApiToken, validate_api_token


@dataclass(frozen=True)
class ApiIdentity:
    user: object
    auth_mode: str
    token: object = None

    @property
    def token_prefix(self):
        return self.token.prefix if self.token is not None else None


class InvalidApiAuthentication(Exception):
    """Raised when an API authentication header is invalid or absent."""


def _get_authorization_header(request):
    return request.META.get("HTTP_AUTHORIZATION")


def _parse_bearer_header(header):
    if not isinstance(header, str) or not header:
        raise InvalidApiAuthentication("Autenticación API inválida.")
    if not header.startswith("Bearer ") or header.count(" ") != 1:
        raise InvalidApiAuthentication("Autenticación API inválida.")

    token_value = header[len("Bearer "):]
    if not token_value or any(character.isspace() for character in token_value):
        raise InvalidApiAuthentication("Autenticación API inválida.")
    return token_value


def resolve_api_identity(request):
    authorization = _get_authorization_header(request)
    if authorization is not None:
        token_value = _parse_bearer_header(authorization)
        try:
            api_token = validate_api_token(token_value)
        except InvalidApiToken as exc:
            raise InvalidApiAuthentication("Autenticación API inválida.") from exc
        return ApiIdentity(user=api_token.user, auth_mode="bearer", token=api_token)

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return ApiIdentity(user=user, auth_mode="session")

    raise InvalidApiAuthentication("Autenticación API requerida.")
