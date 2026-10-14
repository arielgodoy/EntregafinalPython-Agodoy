from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone as datetime_timezone
import json
import logging
import re
import sys
from typing import Any, Generator, Sequence

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import DateTimeField, JSONField
from django.utils import timezone

from settings.services.mysql_connections import MySQLConnectionOpenError

from ..models import Persona
from .connection_roles import EvaluacionesConnectionError, open_evaluaciones_connection

logger = logging.getLogger(__name__)

_BASE_ROLE = "BASE_EVALUACIONES"
_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PersonaStorageError(RuntimeError):
    pass


class DjangoPersonaStorage:
    def __init__(self, alias: str) -> None:
        self.alias = alias

    @contextmanager
    def atomic(self) -> Generator[None, None, None]:
        with transaction.atomic(using=self.alias):
            yield

    def existing_by_month_and_rut(
        self,
        *,
        anio: int,
        mes: int,
        rut_normalizados: Sequence[str],
    ) -> dict[str, Persona]:
        existing: dict[str, Persona] = {}
        for batch in _chunks(rut_normalizados, 200):
            rows = (
                Persona.objects.using(self.alias)
                .filter(
                    anio=anio,
                    mes=mes,
                    rut_normalizado__in=batch,
                )
                .defer("buk_payload")
            )
            existing.update((row.rut_normalizado, row) for row in rows)
        return existing

    def bulk_create(self, personas: Sequence[Persona], batch_size: int) -> None:
        if personas:
            Persona.objects.using(self.alias).bulk_create(
                personas,
                batch_size=batch_size,
            )

    def bulk_update(
        self,
        personas: Sequence[Persona],
        fields: Sequence[str],
        batch_size: int,
    ) -> None:
        if personas:
            Persona.objects.using(self.alias).bulk_update(
                personas,
                fields,
                batch_size=batch_size,
            )

    def list_people(self, limit: int) -> list[Persona]:
        return list(
            Persona.objects.using(self.alias)
            .all()
            .defer("buk_payload")
            .order_by("-anio", "-mes", "full_name")[:limit]
        )

    def list_available_periods(self) -> list[tuple[int, int]]:
        return list(
            Persona.objects.using(self.alias)
            .values_list("anio", "mes")
            .distinct()
            .order_by("-anio", "-mes")
        )

    def list_people_for_period(self, anio: int, mes: int) -> list[Persona]:
        return list(
            Persona.objects.using(self.alias)
            .filter(anio=anio, mes=mes)
            .defer("buk_payload")
            .order_by("full_name")
        )

    def count(self) -> int:
        return Persona.objects.using(self.alias).count()


class MySQLPersonaStorage:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @contextmanager
    def atomic(self) -> Generator[None, None, None]:
        started = False
        try:
            self.connection.begin()
            started = True
            yield
            self.connection.commit()
            started = False
        except BaseException:
            if started:
                self.connection.rollback()
            raise

    def existing_by_month_and_rut(
        self,
        *,
        anio: int,
        mes: int,
        rut_normalizados: Sequence[str],
    ) -> dict[str, Persona]:
        fields = _persona_fields_without_payload()
        columns = ", ".join(_quote_identifier(field.column) for field in fields)
        table = _quote_identifier(Persona._meta.db_table)
        anio_column = _quote_identifier(Persona._meta.get_field("anio").column)
        mes_column = _quote_identifier(Persona._meta.get_field("mes").column)
        rut_column = _quote_identifier(
            Persona._meta.get_field("rut_normalizado").column
        )
        existing: dict[str, Persona] = {}

        for batch in _chunks(rut_normalizados, 200):
            placeholders = ", ".join(["%s"] * len(batch))
            query = (
                f"SELECT {columns} FROM {table} "
                f"WHERE {anio_column} = %s AND {mes_column} = %s "
                f"AND {rut_column} IN ({placeholders})"
            )
            with _cursor(self.connection) as cursor:
                cursor.execute(query, (anio, mes, *batch))
                for row in cursor.fetchall():
                    values = {
                        field.attname: _from_mysql_value(field, value)
                        for field, value in zip(fields, row)
                    }
                    persona = Persona(**values)
                    existing[persona.rut_normalizado] = persona
        return existing

    def bulk_create(self, personas: Sequence[Persona], batch_size: int) -> None:
        if not personas:
            return

        fields = [field for field in _concrete_fields() if not field.primary_key]
        columns = ", ".join(_quote_identifier(field.column) for field in fields)
        placeholders = ", ".join(["%s"] * len(fields))
        query = (
            f"INSERT INTO {_quote_identifier(Persona._meta.db_table)} "
            f"({columns}) VALUES ({placeholders})"
        )
        for batch in _chunks(personas, batch_size):
            values = [
                tuple(
                    _to_mysql_value(field, getattr(persona, field.attname))
                    for field in fields
                )
                for persona in batch
            ]
            with _cursor(self.connection) as cursor:
                cursor.executemany(query, values)

    def bulk_update(
        self,
        personas: Sequence[Persona],
        fields: Sequence[str],
        batch_size: int,
    ) -> None:
        if not personas:
            return

        update_fields = [_get_field(name) for name in fields]
        primary_key = Persona._meta.pk
        assignments = ", ".join(
            f"{_quote_identifier(field.column)} = %s" for field in update_fields
        )
        query = (
            f"UPDATE {_quote_identifier(Persona._meta.db_table)} "
            f"SET {assignments} WHERE {_quote_identifier(primary_key.column)} = %s"
        )
        for batch in _chunks(personas, batch_size):
            values = [
                tuple(
                    _to_mysql_value(field, getattr(persona, field.attname))
                    for field in update_fields
                )
                + (getattr(persona, primary_key.attname),)
                for persona in batch
            ]
            with _cursor(self.connection) as cursor:
                cursor.executemany(query, values)

    def list_people(self, limit: int) -> list[Persona]:
        fields = _persona_fields_without_payload()
        columns = ", ".join(_quote_identifier(field.column) for field in fields)
        ordering = _mysql_ordering()
        query = (
            f"SELECT {columns} FROM {_quote_identifier(Persona._meta.db_table)}"
            f"{ordering} LIMIT %s"
        )
        with _cursor(self.connection) as cursor:
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

        return [
            Persona(**{
                field.attname: _from_mysql_value(field, value)
                for field, value in zip(fields, row)
            })
            for row in rows
        ]

    def list_available_periods(self) -> list[tuple[int, int]]:
        anio_column = _quote_identifier(Persona._meta.get_field("anio").column)
        mes_column = _quote_identifier(Persona._meta.get_field("mes").column)
        query = (
                f"SELECT DISTINCT {anio_column}, {mes_column} "
                f"FROM {_quote_identifier(Persona._meta.db_table)} "
                f"ORDER BY {anio_column} DESC, {mes_column} DESC"
        )
        with _cursor(self.connection) as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
        return [(int(anio), int(mes)) for anio, mes in rows]

    def list_people_for_period(self, anio: int, mes: int) -> list[Persona]:
        fields = _persona_fields_without_payload()
        columns = ", ".join(_quote_identifier(field.column) for field in fields)
        anio_column = _quote_identifier(Persona._meta.get_field("anio").column)
        mes_column = _quote_identifier(Persona._meta.get_field("mes").column)
        query = (
                f"SELECT {columns} FROM {_quote_identifier(Persona._meta.db_table)} "
                f"WHERE {anio_column} = %s AND {mes_column} = %s "
                f"ORDER BY {_quote_identifier(Persona._meta.get_field('full_name').column)}"
        )
        with _cursor(self.connection) as cursor:
                cursor.execute(query, (anio, mes))
                rows = cursor.fetchall()
        return [
                Persona(**{
                    field.attname: _from_mysql_value(field, value)
                    for field, value in zip(fields, row)
                })
                for row in rows
        ]

    def count(self) -> int:
        query = (
            f"SELECT COUNT(*) FROM {_quote_identifier(Persona._meta.db_table)}"
        )
        with _cursor(self.connection) as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
        if row is None:
            raise PersonaStorageError("No se recibió el recuento de Personas.")
        return int(row[0])


@contextmanager
def open_persona_storage() -> Generator[DjangoPersonaStorage | MySQLPersonaStorage, None, None]:
    connection_context = open_evaluaciones_connection(_BASE_ROLE)
    try:
        connection = connection_context.__enter__()
    except (EvaluacionesConnectionError, MySQLConnectionOpenError) as exc:
        raise PersonaStorageError("No se pudo resolver BASE_EVALUACIONES.") from exc

    try:
        if isinstance(connection, BaseDatabaseWrapper):
            alias = connection.alias
            if not alias or alias == DEFAULT_DB_ALIAS:
                raise PersonaStorageError(
                    "BASE_EVALUACIONES no puede utilizar el alias default."
                )
            if connection.vendor not in {"mysql", "postgresql", "sqlite"}:
                raise PersonaStorageError(
                    "BASE_EVALUACIONES utiliza un backend Django no admitido."
                )
            storage = DjangoPersonaStorage(alias)
        elif all(
            callable(getattr(connection, method, None))
            for method in ("begin", "commit", "rollback", "cursor")
        ):
            storage = MySQLPersonaStorage(connection)
        else:
            raise PersonaStorageError(
                "BASE_EVALUACIONES no ofrece una conexión transaccional."
            )

        yield storage
    finally:
        connection_context.__exit__(*sys.exc_info())


def list_personas(limit: int = 5000) -> tuple[list[Persona], int]:
    try:
        with open_persona_storage() as storage:
            return storage.list_people(limit), storage.count()
    except Exception as exc:
        logger.error("Persona storage read failed (error_type=%s)", type(exc).__name__)
        raise PersonaStorageError(
            "No se pudo consultar BASE_EVALUACIONES."
        ) from None


def list_persona_period_data(
    requested_period: tuple[int, int] | None = None,
) -> tuple[list[tuple[int, int]], tuple[int, int] | None, list[Persona]]:
    try:
        with open_persona_storage() as storage:
            periods = storage.list_available_periods()
            if not periods:
                return periods, None, []
            selected_period = (
                requested_period
                if requested_period in periods
                else periods[0]
            )
            personas = storage.list_people_for_period(*selected_period)
            return periods, selected_period, personas
    except Exception as exc:
        logger.error(
            "Persona period listing failed (error_type=%s)",
            type(exc).__name__,
        )
        raise PersonaStorageError(
            "No se pudo consultar BASE_EVALUACIONES."
        ) from None


def _concrete_fields() -> list[Any]:
    return list(Persona._meta.concrete_fields)


def _persona_fields_without_payload() -> list[Any]:
    return [
        field
        for field in _concrete_fields()
        if field.name != "buk_payload"
    ]


def _get_field(name: str) -> Any:
    try:
        return Persona._meta.get_field(name)
    except FieldDoesNotExist as exc:
        raise PersonaStorageError("El campo de Persona no está disponible.") from exc


def _quote_identifier(identifier: str) -> str:
    if not _MYSQL_IDENTIFIER.fullmatch(identifier):
        raise PersonaStorageError("Identificador SQL no válido.")
    return f"`{identifier}`"


def _mysql_ordering() -> str:
    ordering = []
    for name in Persona._meta.ordering:
        descending = name.startswith("-")
        field_name = name[1:] if name[:1] in {"-", "+"} else name
        field = _get_field(field_name)
        direction = "DESC" if descending else "ASC"
        ordering.append(f"{_quote_identifier(field.column)} {direction}")
    return f" ORDER BY {', '.join(ordering)}" if ordering else ""


def _to_mysql_value(field: Any, value: Any) -> Any:
    if (
        value is not None
        and isinstance(field, DateTimeField)
        and timezone.is_aware(value)
    ):
        return timezone.make_naive(value, datetime_timezone.utc)
    if isinstance(field, JSONField):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    return value


def _from_mysql_value(field: Any, value: Any) -> Any:
    if isinstance(field, JSONField) and isinstance(value, (str, bytes)):
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)
    if (
        settings.USE_TZ
        and value is not None
        and isinstance(field, DateTimeField)
        and timezone.is_naive(value)
    ):
        return timezone.make_aware(value, datetime_timezone.utc)
    return value


def _chunks(values: Sequence[Any], batch_size: int) -> Generator[Sequence[Any], None, None]:
    if batch_size < 1:
        raise ValueError("batch_size debe ser mayor que cero.")
    for start in range(0, len(values), batch_size):
        yield values[start : start + batch_size]


@contextmanager
def _cursor(connection: Any) -> Generator[Any, None, None]:
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
