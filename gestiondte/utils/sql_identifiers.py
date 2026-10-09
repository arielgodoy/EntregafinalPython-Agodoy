import re


_MYSQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def validate_mysql_identifier(value, *, label="identificador SQL"):
    if not isinstance(value, str) or not _MYSQL_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"El {label} no es válido.")
    return value
