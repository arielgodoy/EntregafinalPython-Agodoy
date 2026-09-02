"""Helpers HTTP compartidos (IP real del cliente, etc)."""


def get_client_ip(request):
    """Extrae la IP real del cliente respetando X-Forwarded-For si existe."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
