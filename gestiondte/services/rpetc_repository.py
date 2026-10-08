from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from typing import Any, Generator, Mapping

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, DatabaseError, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import DateTimeField, JSONField, Model
from django.utils import timezone

from common.database_classification import DatabaseClassification, get_database_classification
from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import open_mysql_connection

from ..models import (
    CesionRPETC,
    CesionRPETCHistorial,
    GestionDTEConnectionRole,
    TareaCesionRPETC,
    TareaRPETC,
)
from .connection_roles import (
    get_gestiondte_connection,
    get_gestiondte_mysql_connection,
)


class RPETCRepositoryConfigurationError(RuntimeError):
    """Raised when serverbasedte cannot safely serve RPETC operations."""


@dataclass(frozen=True)
class RPETCTaskReference:
    pk: int
    id_tarea: str
    empresa_id: str
    created: bool


@dataclass
class RPETCCesionRecord:
    pk: int
    values: dict[str, Any]
    instance: CesionRPETC | None = None

    def __getattr__(self, name: str) -> Any:
        if name in {"id", "pk"}:
            return self.pk
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class RPETCRepository:
    """Private, connection-scoped persistence primitives for the RPETC importer."""

    role = "serverbasedte"
    _SUPPORTED_MYSQL_ENGINES = {
        SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
        SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
    }

    def __init__(self) -> None:
        resolved = get_gestiondte_connection(self.role)
        source_type = resolved.get("type")
        if source_type == "DJANGO":
            alias = resolved.get("alias")
            if not isinstance(alias, str) or not alias:
                raise RPETCRepositoryConfigurationError(
                    "El rol serverbasedte no resolvió un alias Django."
                )
            if alias == DEFAULT_DB_ALIAS:
                raise RPETCRepositoryConfigurationError(
                    "default no puede ser destino operacional de RPETC."
                )
            if get_database_classification(alias) is not DatabaseClassification.SYSTEM:
                raise RPETCRepositoryConfigurationError(
                    "El alias de serverbasedte no está autorizado como destino SYSTEM."
                )
            self._django_alias = alias
            self._mysql_connection = None
            self._database_name = None
            return

        if source_type != "MYSQL_CONFIG":
            raise RPETCRepositoryConfigurationError(
                "El rol serverbasedte resolvió una fuente no soportada."
            )

        connection = get_gestiondte_mysql_connection(self.role)
        if not connection.is_active:
            raise RPETCRepositoryConfigurationError(
                "La conexión configurada para serverbasedte está inactiva."
            )
        engine = SettingsMySQLConnection.normalize_engine(connection.engine)
        if engine not in self._SUPPORTED_MYSQL_ENGINES:
            raise RPETCRepositoryConfigurationError(
                "El motor configurado para serverbasedte no está soportado."
            )

        database_name = resolved.get("database_name")
        if (
            not isinstance(database_name, str)
            or not GestionDTEConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
        ):
            raise RPETCRepositoryConfigurationError(
                "serverbasedte no resolvió una base de datos válida."
            )
        if connection.pk != resolved.get("connection_id"):
            raise RPETCRepositoryConfigurationError(
                "La conexión física de serverbasedte cambió durante la resolución."
            )

        self._django_alias = None
        self._mysql_connection = connection
        self._database_name = database_name

    @contextmanager
    def unit_of_work(self) -> Generator[_DjangoUnitOfWork | _MySQLUnitOfWork, None, None]:
        if self._django_alias is not None:
            with transaction.atomic(using=self._django_alias):
                yield _DjangoUnitOfWork(self._django_alias)
            return

        if self._mysql_connection is None or self._database_name is None:
            raise RPETCRepositoryConfigurationError(
                "La unidad de trabajo RPETC no tiene un destino configurado."
            )

        with open_mysql_connection(
            self._mysql_connection,
            database_name=self._database_name,
        ) as connection:
            if isinstance(connection, BaseDatabaseWrapper):
                alias = connection.alias
                if not alias or alias == DEFAULT_DB_ALIAS:
                    raise RPETCRepositoryConfigurationError(
                        "La conexión MYSQL_CONFIG no abrió un alias operacional aislado."
                    )
                if connection.vendor != "mysql":
                    raise RPETCRepositoryConfigurationError(
                        "MYSQL_CONFIG abrió un backend distinto de MySQL."
                    )
                with transaction.atomic(using=alias):
                    yield _DjangoUnitOfWork(alias)
                return

            if not all(
                callable(getattr(connection, method, None))
                for method in ("begin", "commit", "rollback", "cursor")
            ):
                raise RPETCRepositoryConfigurationError(
                    "La conexión MYSQL_CONFIG no ofrece control transaccional DB-API."
                )
            with _dbapi_transaction(connection):
                yield _MySQLUnitOfWork(connection)


class _DjangoUnitOfWork:
    def __init__(self, alias: str) -> None:
        self.alias = alias

    def upsert_tarea(
        self,
        id_tarea: str,
        defaults: Mapping[str, Any],
    ) -> RPETCTaskReference:
        values = _task_values_with_company_id(defaults)
        task, created = TareaRPETC.objects.using(self.alias).update_or_create(
            id_tarea=id_tarea,
            defaults=values,
        )
        empresa_id = getattr(task, "empresa_id", None)
        if empresa_id is None:
            raise RPETCRepositoryConfigurationError(
                "La tarea RPETC persistida no tiene una identidad de Empresa."
            )
        return RPETCTaskReference(
            pk=_required_pk(task),
            id_tarea=task.id_tarea,
            empresa_id=str(empresa_id),
            created=created,
        )

    def find_cesion(self, identity: Mapping[str, Any]) -> RPETCCesionRecord | None:
        instance = CesionRPETC.objects.using(self.alias).filter(**identity).first()
        if instance is None:
            return None
        return _cession_record(instance)

    def create_cesion(self, values: Mapping[str, Any]) -> RPETCCesionRecord:
        instance = CesionRPETC.objects.using(self.alias).create(**dict(values))
        return _cession_record(instance)

    def update_cesion(
        self,
        cesion: RPETCCesionRecord,
        values: Mapping[str, Any],
    ) -> None:
        if not values:
            return
        if cesion.instance is None:
            raise RPETCRepositoryConfigurationError(
                "La cesión ORM requerida para la actualización no está disponible."
            )
        for name, value in values.items():
            setattr(cesion.instance, name, value)
        update_fields = list(values) + ["actualizada_en"]
        cesion.instance.save(using=self.alias, update_fields=update_fields)
        cesion.values.update(values)
        cesion.values["actualizada_en"] = cesion.instance.actualizada_en

    def create_historial(
        self,
        cesion_id: int,
        estado: str,
        estado_anterior: str | None,
        tarea_id: int,
    ) -> None:
        CesionRPETCHistorial.objects.using(self.alias).create(
            cesion_id=cesion_id,
            estado=estado,
            estado_anterior=estado_anterior,
            tarea_origen_id=tarea_id,
        )

    def get_or_create_vinculo(
        self,
        tarea_id: int,
        cesion_id: int,
        defaults: Mapping[str, Any],
    ) -> tuple[int, bool]:
        vinculo, created = TareaCesionRPETC.objects.using(self.alias).get_or_create(
            tarea_id=tarea_id,
            cesion_id=cesion_id,
            defaults=dict(defaults),
        )
        return vinculo.pk, created


class _MySQLUnitOfWork:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def upsert_tarea(
        self,
        id_tarea: str,
        defaults: Mapping[str, Any],
    ) -> RPETCTaskReference:
        values = _task_values_with_company_id(defaults)
        pk_field = _primary_key_field(TareaRPETC)
        id_field = TareaRPETC._meta.get_field("id_tarea")
        with _cursor(self.connection) as cursor:
            cursor.execute(
                f"SELECT {_quote_mysql(pk_field.column)} "
                f"FROM {_quote_mysql(TareaRPETC._meta.db_table)} "
                f"WHERE {_quote_mysql(id_field.column)} = %s LIMIT 1 FOR UPDATE",
                (id_tarea,),
            )
            row = cursor.fetchone()
            if row is None:
                insert_values = {"id_tarea": id_tarea, **values}
                insert_values["consultada_en"] = timezone.now()
                insert_values["actualizada_en"] = timezone.now()
                try:
                    task_id = _insert(cursor, TareaRPETC, insert_values)
                    created = True
                except _pymysql_integrity_error_type() as exc:
                    if not _is_duplicate_key_error(exc):
                        raise
                    with _cursor(self.connection) as retry_cursor:
                        retry_cursor.execute(
                            f"SELECT {_quote_mysql(pk_field.column)} "
                            f"FROM {_quote_mysql(TareaRPETC._meta.db_table)} "
                            f"WHERE {_quote_mysql(id_field.column)} = %s LIMIT 1 FOR UPDATE",
                            (id_tarea,),
                        )
                        row = retry_cursor.fetchone()
                    if row is None:
                        raise
                    task_id = row[0]
                    values["actualizada_en"] = timezone.now()
                    _update(cursor, TareaRPETC, values, pk_field.attname, task_id)
                    created = False
            else:
                task_id = row[0]
                values["actualizada_en"] = timezone.now()
                _update(cursor, TareaRPETC, values, pk_field.attname, task_id)
                created = False
        return RPETCTaskReference(
            pk=task_id,
            id_tarea=id_tarea,
            empresa_id=str(values["empresa_id"]),
            created=created,
        )

    def find_cesion(self, identity: Mapping[str, Any]) -> RPETCCesionRecord | None:
        fields = list(CesionRPETC._meta.concrete_fields)
        columns = ", ".join(_quote_mysql(field.column) for field in fields)
        where, params = _where(CesionRPETC, identity)
        ordering = _ordering(CesionRPETC)
        sql = (
            f"SELECT {columns} FROM {_quote_mysql(CesionRPETC._meta.db_table)} "
            f"WHERE {where}{ordering} LIMIT 1"
        )
        with _cursor(self.connection) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        if row is None:
            return None
        values = _values_from_row(CesionRPETC, fields, row)
        pk_field = _primary_key_field(CesionRPETC)
        return RPETCCesionRecord(
            pk=values[pk_field.attname],
            values=values,
        )

    def create_cesion(self, values: Mapping[str, Any]) -> RPETCCesionRecord:
        insert_values = dict(values)
        insert_values["detectada_en"] = timezone.now()
        insert_values["actualizada_en"] = timezone.now()
        with _cursor(self.connection) as cursor:
            cesion_id = _insert(cursor, CesionRPETC, insert_values)
        record_values = {
            _field_for_name(CesionRPETC, name).attname: value
            for name, value in insert_values.items()
        }
        record_values[_primary_key_field(CesionRPETC).attname] = cesion_id
        return RPETCCesionRecord(pk=cesion_id, values=record_values)

    def update_cesion(
        self,
        cesion: RPETCCesionRecord,
        values: Mapping[str, Any],
    ) -> None:
        if not values:
            return
        update_values = dict(values)
        update_values["actualizada_en"] = timezone.now()
        with _cursor(self.connection) as cursor:
            _update(
                cursor,
                CesionRPETC,
                update_values,
                _primary_key_field(CesionRPETC).attname,
                cesion.pk,
            )
        cesion.values.update(values)
        cesion.values["actualizada_en"] = update_values["actualizada_en"]

    def create_historial(
        self,
        cesion_id: int,
        estado: str,
        estado_anterior: str | None,
        tarea_id: int,
    ) -> None:
        with _cursor(self.connection) as cursor:
            _insert(
                cursor,
                CesionRPETCHistorial,
                {
                    "cesion_id": cesion_id,
                    "estado": estado,
                    "estado_anterior": estado_anterior,
                    "tarea_origen_id": tarea_id,
                    "fecha_detectado": timezone.now(),
                    "observacion": None,
                },
            )

    def get_or_create_vinculo(
        self,
        tarea_id: int,
        cesion_id: int,
        defaults: Mapping[str, Any],
    ) -> tuple[int, bool]:
        model = TareaCesionRPETC
        pk_field = _primary_key_field(model)
        identity = {"tarea_id": tarea_id, "cesion_id": cesion_id}
        where, params = _where(model, identity)
        with _cursor(self.connection) as cursor:
            cursor.execute(
                f"SELECT {_quote_mysql(pk_field.column)} "
                f"FROM {_quote_mysql(model._meta.db_table)} "
                f"WHERE {where} LIMIT 1",
                params,
            )
            row = cursor.fetchone()
            if row is not None:
                return row[0], False
            insert_values = {**identity, **dict(defaults)}
            insert_values["fecha_detectada"] = timezone.now()
            try:
                return _insert(cursor, model, insert_values), True
            except _pymysql_integrity_error_type() as exc:
                if not _is_duplicate_key_error(exc):
                    raise
                cursor.execute(
                    f"SELECT {_quote_mysql(pk_field.column)} "
                    f"FROM {_quote_mysql(model._meta.db_table)} "
                    f"WHERE {where} LIMIT 1 FOR UPDATE",
                    params,
                )
                row = cursor.fetchone()
                if row is None:
                    raise
                return row[0], False


@contextmanager
def _dbapi_transaction(connection: Any) -> Generator[None, None, None]:
    started = False
    try:
        connection.begin()
        started = True
        yield
        connection.commit()
        started = False
    except BaseException:
        if started:
            connection.rollback()
        raise


@contextmanager
def _cursor(connection: Any) -> Generator[Any, None, None]:
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def _task_values_with_company_id(values: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(values)
    empresa = result.pop("empresa", None)
    if empresa is not None:
        result["empresa_id"] = getattr(empresa, "codigo", empresa)
    if result.get("empresa_id") is None:
        raise RPETCRepositoryConfigurationError(
            "La persistencia RPETC requiere la identidad canónica de Empresa."
        )
    return result


def _cession_record(instance: CesionRPETC) -> RPETCCesionRecord:
    pk = _required_pk(instance)
    values = {
        field.attname: getattr(instance, field.attname)
        for field in CesionRPETC._meta.concrete_fields
    }
    return RPETCCesionRecord(pk=pk, values=values, instance=instance)


def _required_pk(instance: Model) -> int:
    pk = instance.pk
    if pk is None:
        raise RPETCRepositoryConfigurationError(
            f"El modelo {instance.__class__.__name__} no tiene una PK persistida."
        )
    return pk


def _primary_key_field(model: type[Model]):
    field = model._meta.pk
    if field is None:
        raise RPETCRepositoryConfigurationError(
            f"El modelo {model.__name__} no tiene una PK definida."
        )
    return field


def _field_for_name(model: type[Model], name: str):
    for field in model._meta.concrete_fields:
        if name in {field.name, field.attname}:
            return field
    raise RPETCRepositoryConfigurationError(
        f"El campo {name!r} no pertenece al modelo {model.__name__}."
    )


def _quote_mysql(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _where(model: type[Model], values: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    clauses = []
    params = []
    for name, value in values.items():
        field = _field_for_name(model, name)
        clauses.append(f"{_quote_mysql(field.column)} = %s")
        params.append(_to_database_value(field, value))
    return " AND ".join(clauses), tuple(params)


def _ordering(model: type[Model]) -> str:
    ordering = model._meta.ordering
    if not ordering:
        return ""
    items = []
    for value in ordering:
        descending = value.startswith("-")
        name = value[1:] if value[:1] in {"-", "+"} else value
        field = _field_for_name(model, name)
        items.append(f"{_quote_mysql(field.column)} {'DESC' if descending else 'ASC'}")
    return f" ORDER BY {', '.join(items)}"


def _insert(cursor: Any, model: type[Model], values: Mapping[str, Any]) -> int:
    fields = [_field_for_name(model, name) for name in values]
    columns = ", ".join(_quote_mysql(field.column) for field in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    cursor.execute(
        f"INSERT INTO {_quote_mysql(model._meta.db_table)} ({columns}) "
        f"VALUES ({placeholders})",
        tuple(_to_database_value(field, value) for field, value in zip(fields, values.values())),
    )
    pk = cursor.lastrowid
    if pk is None:
        raise RPETCRepositoryConfigurationError(
            f"MySQL no devolvió la PK insertada para {model.__name__}."
        )
    return pk


def _update(
    cursor: Any,
    model: type[Model],
    values: Mapping[str, Any],
    identity_name: str,
    identity_value: Any,
) -> None:
    fields = [_field_for_name(model, name) for name in values]
    assignments = ", ".join(f"{_quote_mysql(field.column)} = %s" for field in fields)
    identity_field = _field_for_name(model, identity_name)
    params = tuple(
        _to_database_value(field, value)
        for field, value in zip(fields, values.values())
    ) + (_to_database_value(identity_field, identity_value),)
    cursor.execute(
        f"UPDATE {_quote_mysql(model._meta.db_table)} SET {assignments} "
        f"WHERE {_quote_mysql(identity_field.column)} = %s",
        params,
    )
    if cursor.rowcount == 0:
        cursor.execute(
            f"SELECT 1 FROM {_quote_mysql(model._meta.db_table)} "
            f"WHERE {_quote_mysql(identity_field.column)} = %s",
            (_to_database_value(identity_field, identity_value),),
        )
        if cursor.fetchone() is None:
            raise DatabaseError(
                f"La actualización RPETC no encontró {model.__name__}."
            )


def _pymysql_integrity_error_type() -> type[Exception]:
    from pymysql.err import IntegrityError as PyMySQLIntegrityError

    return PyMySQLIntegrityError


def _is_duplicate_key_error(error: Exception) -> bool:
    return bool(error.args) and error.args[0] == 1062


def _to_database_value(field: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(field, JSONField):
        kwargs: dict[str, Any] = {"ensure_ascii": False}
        if field.encoder is not None:
            kwargs["cls"] = field.encoder
        return json.dumps(value, **kwargs)
    if isinstance(field, DateTimeField) and timezone.is_aware(value):
        return timezone.make_naive(value, datetime_timezone.utc)
    return value


def _values_from_row(
    model: type[Model],
    fields: list[Any],
    row: tuple[Any, ...],
) -> dict[str, Any]:
    if len(fields) != len(row):
        raise RPETCRepositoryConfigurationError(
            f"El resultado MySQL no coincide con las columnas de {model.__name__}."
        )
    values = {}
    for field, raw_value in zip(fields, row):
        value = raw_value
        if value is not None and isinstance(field, JSONField) and isinstance(value, str):
            value = json.loads(value)
        elif (
            settings.USE_TZ
            and value is not None
            and isinstance(field, DateTimeField)
            and isinstance(value, datetime)
            and timezone.is_naive(value)
        ):
            value = timezone.make_aware(value, datetime_timezone.utc)
        values[field.attname] = value
    return values
