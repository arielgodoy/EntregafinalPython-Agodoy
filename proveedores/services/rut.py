import re

from django.core.exceptions import ValidationError


_SEPARADORES_RUT = re.compile(r"[.\-\s]")


def normalizar_rut(value):
    """Devuelve el RUT chileno en formato cuerpo-DV, o None si esta vacio."""
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    limpio = _SEPARADORES_RUT.sub("", raw).upper()
    if len(limpio) < 2:
        raise ValidationError("El RUT debe incluir cuerpo y digito verificador.")

    cuerpo, digito = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit() or digito not in "0123456789K":
        raise ValidationError("El RUT tiene un formato invalido.")

    cuerpo = cuerpo.lstrip("0") or "0"
    if len(cuerpo) > 8:
        raise ValidationError("El cuerpo del RUT no es valido.")

    return f"{cuerpo}-{digito}"


def validar_rut(value):
    """Valida un RUT chileno usando el algoritmo modulo 11."""
    rut = normalizar_rut(value)
    if rut is None:
        return

    cuerpo, digito = rut.split("-", 1)
    suma = 0
    factor = 2
    for numero in reversed(cuerpo):
        suma += int(numero) * factor
        factor = factor + 1 if factor < 7 else 2

    resto = 11 - (suma % 11)
    esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    if digito != esperado:
        raise ValidationError("El RUT es invalido.")
