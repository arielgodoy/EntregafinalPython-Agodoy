"""Configurable storage boundary for quotation rounds, quotations and documents."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from access_control.models import Empresa
from proveedores.models import Proveedor
from settings.services.mysql_connections import open_mysql_connection
from tareas.models import Cotizacion, DocumentoCotizacion, RondaCotizacion, Tarea
from tareas.services.connection_roles import (
    TareaConnectionError,
    resolve_operational_backend,
)
from tareas.services.image_processing import optimize_uploaded_image

logger = logging.getLogger(__name__)


class QuotationStorageError(RuntimeError):
    """A controlled failure while resolving or using quotation storage."""


class QuotationNotFound(QuotationStorageError):
    """The quotation object is absent from the configured operational backend."""


@dataclass(frozen=True)
class QuotationRoundData:
    id: int
    task_id: int
    company_id: int
    number: int
    minimum: int
    state: str
    opened_at: object
    closed_at: object


@dataclass(frozen=True)
class QuotationData:
    id: int
    round_id: int
    provider_id: int | None
    version: int
    amount: Decimal
    current: bool
    state: str
    quote_date: object
    notes: str


@dataclass(frozen=True)
class QuotationDocumentData:
    id: int
    quotation_id: int
    file_format: str
    file_name: str
    url: str
    user_id: int
    created_at: object


def _field_clean(model, values, excluded=()):
    instance = model(**values)
    instance.full_clean(
        exclude=list(excluded),
        validate_unique=False,
        validate_constraints=False,
    )
    return instance


def _provider_id(provider_id):
    if provider_id is None:
        raise ValidationError("PROVIDER_REQUIRED: La cotización requiere un proveedor.")
    if not Proveedor.objects.using("default").filter(pk=provider_id).exists():
        raise ValidationError("PROVIDER_INVALID: Debe indicar un proveedor local válido.")
    return provider_id


def _user_id(user_id):
    try:
        User.objects.using("default").only("pk").get(pk=user_id)
    except User.DoesNotExist as exc:
        raise ValidationError("El usuario indicado no existe.") from exc
    return user_id


def _company_exists(company_id):
    try:
        Empresa.objects.using("default").only("pk").get(pk=company_id)
    except Empresa.DoesNotExist as exc:
        raise ValidationError("La Empresa indicada no existe.") from exc


def _round_values(row):
    return QuotationRoundData(*row)


def _quotation_values(row):
    return QuotationData(
        *row[:4],
        Decimal(str(row[4])),
        bool(row[5]),
        *row[6:],
    )


class DjangoQuotationStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def _task(self, task_id, company_id=None, *, lock=False):
        queryset = Tarea.objects.using(self.alias)
        if lock:
            queryset = queryset.select_for_update()
        filters = {"pk": task_id}
        if company_id is not None:
            filters["empresa_id"] = company_id
        try:
            return queryset.get(**filters)
        except Tarea.DoesNotExist as exc:
            raise QuotationNotFound("La tarea no existe en BASE_TAREAS.") from exc

    def _round(self, round_id, *, lock=False):
        queryset = RondaCotizacion.objects.using(self.alias)
        if lock:
            queryset = queryset.select_for_update()
        try:
            return queryset.get(pk=round_id)
        except RondaCotizacion.DoesNotExist as exc:
            raise QuotationNotFound("La ronda no existe en BASE_TAREAS.") from exc

    def round_data(self, round_id):
        row = (
            RondaCotizacion.objects.using(self.alias)
            .filter(pk=round_id)
            .values_list(
                "pk", "tarea_id", "tarea__empresa_id", "numero",
                "minimo_cotizaciones", "estado", "fecha_apertura", "fecha_cierre",
            )
            .first()
        )
        return _round_values(row) if row else None

    def quotation_data(self, quotation_id, *, round_id=None):
        filters = {"pk": quotation_id}
        if round_id is not None:
            filters["ronda_id"] = round_id
        row = (
            Cotizacion.objects.using(self.alias)
            .filter(**filters)
            .values_list(
                "pk", "ronda_id", "proveedor_id", "version", "monto",
                "vigente", "estado", "fecha_cotizacion", "observaciones",
            )
            .first()
        )
        return _quotation_values(row) if row else None

    def document_data(self, document_id):
        row = (
            DocumentoCotizacion.objects.using(self.alias)
            .filter(pk=document_id)
            .values_list(
                "pk", "cotizacion_id", "formato_archivo", "archivo", "url",
                "usuario_id", "fecha",
            )
            .first()
        )
        return QuotationDocumentData(*row) if row else None

    def get_next_round_number(self, task_id, company_id=None):
        self._task(task_id, company_id)
        last = (
            RondaCotizacion.objects.using(self.alias)
            .filter(tarea_id=task_id)
            .aggregate(last=Max("numero"))["last"]
            or 0
        )
        return last + 1

    def get_latest_round(self, task_id, company_id=None):
        self._task(task_id, company_id)
        round_id = (
            RondaCotizacion.objects.using(self.alias)
            .filter(tarea_id=task_id)
            .order_by("-numero")
            .values_list("pk", flat=True)
            .first()
        )
        return self.round_data(round_id) if round_id else None

    def has_quotation_process(self, task_id, company_id=None):
        self._task(task_id, company_id)
        return RondaCotizacion.objects.using(self.alias).filter(tarea_id=task_id).exists()

    def count_available_quotations(self, round_id):
        return (
            Cotizacion.objects.using(self.alias)
            .filter(ronda_id=round_id, vigente=True, proveedor_id__isnull=False)
            .values("proveedor_id")
            .distinct()
            .count()
        )

    def round_minimum_met(self, round_id):
        ronda = self._round(round_id)
        return self.count_available_quotations(round_id) >= ronda.minimo_cotizaciones

    def create_round(self, *, task_id, company_id, minimum, opened_at=None):
        _company_exists(company_id)
        with transaction.atomic(using=self.alias):
            task = self._task(task_id, company_id, lock=True)
            last = (
                RondaCotizacion.objects.using(self.alias)
                .filter(tarea_id=task_id)
                .aggregate(last=Max("numero"))["last"]
                or 0
            )
            values = {
                "tarea_id": task.pk,
                "numero": last + 1,
                "minimo_cotizaciones": minimum,
            }
            if opened_at is not None:
                values["fecha_apertura"] = opened_at
            ronda = _field_clean(RondaCotizacion, values, excluded=("tarea",))
            ronda.save(using=self.alias)
            return self.round_data(ronda.pk)

    def close_round(self, *, round_id):
        with transaction.atomic(using=self.alias):
            ronda = self._round(round_id, lock=True)
            if ronda.estado == RondaCotizacion.Estado.CERRADA:
                return self.round_data(round_id)
            if self.count_available_quotations(round_id) < ronda.minimo_cotizaciones:
                raise ValidationError(
                    "QUOTATION_MINIMUM_NOT_MET: La ronda no cumple el mínimo de cotizaciones vigentes."
                )
            ronda.estado = RondaCotizacion.Estado.CERRADA
            ronda.fecha_cierre = timezone.now()
            _field_clean(
                RondaCotizacion,
                {
                    "tarea_id": ronda.tarea_id,
                    "numero": ronda.numero,
                    "minimo_cotizaciones": ronda.minimo_cotizaciones,
                    "estado": ronda.estado,
                    "fecha_apertura": ronda.fecha_apertura,
                    "fecha_cierre": ronda.fecha_cierre,
                },
                excluded=("tarea",),
            )
            ronda.save(using=self.alias, update_fields=["estado", "fecha_cierre"])
            return self.round_data(round_id)

    def open_next_round(self, *, round_id, company_id=None):
        with transaction.atomic(using=self.alias):
            previous = self._round(round_id, lock=True)
            task = self._task(previous.tarea_id, company_id, lock=True)
            last = (
                RondaCotizacion.objects.using(self.alias)
                .filter(tarea_id=task.pk)
                .aggregate(last=Max("numero"))["last"]
                or 0
            )
            ronda = _field_clean(
                RondaCotizacion,
                {
                    "tarea_id": task.pk,
                    "numero": last + 1,
                    "minimo_cotizaciones": previous.minimo_cotizaciones,
                },
                excluded=("tarea",),
            )
            ronda.save(using=self.alias)
            return self.round_data(ronda.pk)

    def create_quotation(
        self, *, round_id, provider_id, version, amount, current, state,
        quote_date, notes="",
    ):
        _provider_id(provider_id)
        if version < 1 or version > 3:
            raise ValidationError("QUOTATION_VERSION_OUT_OF_RANGE: La versión debe estar entre 1 y 3.")
        with transaction.atomic(using=self.alias):
            self._round(round_id, lock=True)
            versions = Cotizacion.objects.using(self.alias).filter(
                ronda_id=round_id, proveedor_id=provider_id,
            )
            if versions.filter(version=version).exists():
                raise ValidationError(
                    "QUOTATION_VERSION_DUPLICATE: La versión ya existe para este proveedor y ronda."
                )
            if versions.count() >= 3:
                raise ValidationError(
                    "QUOTATION_VERSION_LIMIT: El proveedor ya tiene tres versiones en esta ronda."
                )
            quotation = _field_clean(
                Cotizacion,
                {
                    "ronda_id": round_id,
                    "proveedor_id": provider_id,
                    "version": version,
                    "monto": amount,
                    "vigente": current,
                    "estado": state,
                    "fecha_cotizacion": quote_date,
                    "observaciones": notes,
                },
                excluded=("ronda", "proveedor"),
            )
            quotation.save(using=self.alias)
            return self.quotation_data(quotation.pk)

    def update_quotation_status(self, *, quotation_id, state, round_id=None):
        filters = {"pk": quotation_id}
        if round_id is not None:
            filters["ronda_id"] = round_id
        with transaction.atomic(using=self.alias):
            try:
                quotation = (
                    Cotizacion.objects.using(self.alias)
                    .select_for_update()
                    .get(**filters)
                )
            except Cotizacion.DoesNotExist as exc:
                raise QuotationNotFound("La cotización no existe en BASE_TAREAS.") from exc
            quotation.estado = state
            clean = {
                "ronda_id": quotation.ronda_id,
                "proveedor_id": quotation.proveedor_id,
                "version": quotation.version,
                "monto": quotation.monto,
                "vigente": quotation.vigente,
                "estado": quotation.estado,
                "fecha_cotizacion": quotation.fecha_cotizacion,
                "observaciones": quotation.observaciones,
            }
            _field_clean(Cotizacion, clean, excluded=("ronda", "proveedor"))
            quotation.save(using=self.alias, update_fields=["estado"])
            return self.quotation_data(quotation.pk)

    def add_quotation_document(
        self, *, quotation_id, format, user_id, uploaded_file=None, url="", created_at=None,
    ):
        _user_id(user_id)
        uploaded_file = optimize_uploaded_image(uploaded_file, format)
        document = DocumentoCotizacion(
            cotizacion_id=quotation_id,
            formato_archivo=format,
            archivo=getattr(uploaded_file, "name", "") if uploaded_file else "",
            url=url or "",
            usuario_id=user_id,
        )
        if created_at is not None:
            document.fecha = created_at
        document.full_clean(
            exclude=["cotizacion", "usuario"],
            validate_unique=False,
            validate_constraints=False,
        )
        saved_name = ""
        if uploaded_file:
            document.archivo.save(
                getattr(uploaded_file, "name", "archivo"),
                uploaded_file,
                save=False,
            )
            saved_name = document.archivo.name
        try:
            with transaction.atomic(using=self.alias):
                self._quotation_for_document(quotation_id)
                document.save(using=self.alias)
                return self.document_data(document.pk)
        except Exception:
            if saved_name:
                document.archivo.storage.delete(saved_name)
            raise

    def _quotation_for_document(self, quotation_id):
        if not Cotizacion.objects.using(self.alias).filter(pk=quotation_id).exists():
            raise QuotationNotFound("La cotización no existe en BASE_TAREAS.")

    def materialize_round(self, round_id):
        return RondaCotizacion.objects.using(self.alias).get(pk=round_id)

    def materialize_quotation(self, quotation_id):
        return Cotizacion.objects.using(self.alias).get(pk=quotation_id)

    def materialize_document(self, document_id):
        return DocumentoCotizacion.objects.using(self.alias).get(pk=document_id)


class MySQLQuotationStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def _connection(self):
        return open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        )

    @staticmethod
    def _task(cursor, task_id, company_id=None, *, lock=False):
        sql = "SELECT id, empresa_id FROM tareas_tarea WHERE id=%s"
        params = [task_id]
        if company_id is not None:
            sql += " AND empresa_id=%s"
            params.append(company_id)
        if lock:
            sql += " FOR UPDATE"
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        if row is None:
            raise QuotationNotFound("La tarea no existe en BASE_TAREAS.")
        return row

    @staticmethod
    def _round(cursor, round_id, *, lock=False):
        sql = (
            "SELECT r.id, r.tarea_id, t.empresa_id, r.numero, r.minimo_cotizaciones, "
            "r.estado, r.fecha_apertura, r.fecha_cierre "
            "FROM tareas_rondacotizacion r "
            "JOIN tareas_tarea t ON t.id=r.tarea_id WHERE r.id=%s"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor.execute(sql, (round_id,))
        row = cursor.fetchone()
        return _round_values(row) if row else None

    @staticmethod
    def _quotation(cursor, quotation_id, round_id=None, *, lock=False):
        sql = (
            "SELECT id, ronda_id, proveedor_id, version, monto, vigente, estado, "
            "fecha_cotizacion, observaciones FROM tareas_cotizacion WHERE id=%s"
        )
        params = [quotation_id]
        if round_id is not None:
            sql += " AND ronda_id=%s"
            params.append(round_id)
        if lock:
            sql += " FOR UPDATE"
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        return _quotation_values(row) if row else None

    @staticmethod
    def _document(cursor, document_id):
        cursor.execute(
            "SELECT id, cotizacion_id, formato_archivo, archivo, url, usuario_id, fecha "
            "FROM tareas_documentocotizacion WHERE id=%s",
            (document_id,),
        )
        row = cursor.fetchone()
        return QuotationDocumentData(*row) if row else None

    def get_next_round_number(self, task_id, company_id=None):
        _company_exists(company_id) if company_id is not None else None
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                self._task(cursor, task_id, company_id)
                cursor.execute(
                    "SELECT COALESCE(MAX(numero), 0) FROM tareas_rondacotizacion WHERE tarea_id=%s",
                    (task_id,),
                )
                return int(cursor.fetchone()[0]) + 1
            finally:
                cursor.close()

    def get_latest_round(self, task_id, company_id=None):
        if company_id is not None:
            _company_exists(company_id)
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                self._task(cursor, task_id, company_id)
                cursor.execute(
                    "SELECT id FROM tareas_rondacotizacion WHERE tarea_id=%s "
                    "ORDER BY numero DESC LIMIT 1",
                    (task_id,),
                )
                row = cursor.fetchone()
                return self._round(cursor, row[0]) if row else None
            finally:
                cursor.close()

    def has_quotation_process(self, task_id, company_id=None):
        if company_id is not None:
            _company_exists(company_id)
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                self._task(cursor, task_id, company_id)
                cursor.execute(
                    "SELECT 1 FROM tareas_rondacotizacion WHERE tarea_id=%s LIMIT 1",
                    (task_id,),
                )
                return cursor.fetchone() is not None
            finally:
                cursor.close()

    def count_available_quotations(self, round_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                if self._round(cursor, round_id) is None:
                    raise QuotationNotFound("La ronda no existe en BASE_TAREAS.")
                cursor.execute(
                    "SELECT COUNT(DISTINCT proveedor_id) FROM tareas_cotizacion "
                    "WHERE ronda_id=%s AND vigente=1 AND proveedor_id IS NOT NULL",
                    (round_id,),
                )
                return int(cursor.fetchone()[0])
            finally:
                cursor.close()

    def round_minimum_met(self, round_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                ronda = self._round(cursor, round_id)
                if ronda is None:
                    raise QuotationNotFound("La ronda no existe en BASE_TAREAS.")
                count = self._count_available(cursor, round_id)
                return count >= ronda.minimum
            finally:
                cursor.close()

    @staticmethod
    def _count_available(cursor, round_id):
        cursor.execute(
            "SELECT COUNT(DISTINCT proveedor_id) FROM tareas_cotizacion "
            "WHERE ronda_id=%s AND vigente=1 AND proveedor_id IS NOT NULL",
            (round_id,),
        )
        return int(cursor.fetchone()[0])

    def create_round(self, *, task_id, company_id, minimum, opened_at=None):
        _company_exists(company_id)
        if opened_at is None:
            opened_at = timezone.now()
        ronda = _field_clean(
            RondaCotizacion,
            {
                "tarea_id": task_id,
                "numero": 1,
                "minimo_cotizaciones": minimum,
                "fecha_apertura": opened_at,
            },
            excluded=("tarea",),
        )
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("START TRANSACTION")
                self._task(cursor, task_id, company_id, lock=True)
                cursor.execute(
                    "SELECT numero FROM tareas_rondacotizacion WHERE tarea_id=%s "
                    "ORDER BY numero DESC LIMIT 1 FOR UPDATE",
                    (task_id,),
                )
                last = cursor.fetchone()
                number = int(last[0]) + 1 if last else 1
                cursor.execute(
                    "INSERT INTO tareas_rondacotizacion "
                    "(tarea_id,numero,minimo_cotizaciones,estado,fecha_apertura,fecha_cierre) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        task_id, number, minimum, RondaCotizacion.Estado.ABIERTA,
                        opened_at, None,
                    ),
                )
                result = self._round(cursor, cursor.lastrowid)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def close_round(self, *, round_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("START TRANSACTION")
                ronda = self._round(cursor, round_id, lock=True)
                if ronda is None:
                    raise QuotationNotFound("La ronda no existe en BASE_TAREAS.")
                if ronda.state == RondaCotizacion.Estado.CERRADA:
                    connection.commit()
                    return ronda
                if self._count_available(cursor, round_id) < ronda.minimum:
                    raise ValidationError(
                        "QUOTATION_MINIMUM_NOT_MET: La ronda no cumple el mínimo de cotizaciones vigentes."
                    )
                closed_at = timezone.now()
                cursor.execute(
                    "UPDATE tareas_rondacotizacion SET estado=%s, fecha_cierre=%s WHERE id=%s",
                    (RondaCotizacion.Estado.CERRADA, closed_at, round_id),
                )
                result = self._round(cursor, round_id)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def open_next_round(self, *, round_id, company_id=None):
        if company_id is not None:
            _company_exists(company_id)
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("START TRANSACTION")
                previous = self._round(cursor, round_id, lock=True)
                if previous is None:
                    raise QuotationNotFound("La ronda no existe en BASE_TAREAS.")
                self._task(cursor, previous.task_id, company_id, lock=True)
                cursor.execute(
                    "SELECT numero FROM tareas_rondacotizacion WHERE tarea_id=%s "
                    "ORDER BY numero DESC LIMIT 1 FOR UPDATE",
                    (previous.task_id,),
                )
                last = cursor.fetchone()
                number = int(last[0]) + 1 if last else 1
                opened_at = timezone.now()
                cursor.execute(
                    "INSERT INTO tareas_rondacotizacion "
                    "(tarea_id,numero,minimo_cotizaciones,estado,fecha_apertura,fecha_cierre) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        previous.task_id, number, previous.minimum,
                        RondaCotizacion.Estado.ABIERTA, opened_at, None,
                    ),
                )
                result = self._round(cursor, cursor.lastrowid)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def create_quotation(
        self, *, round_id, provider_id, version, amount, current, state,
        quote_date, notes="",
    ):
        _provider_id(provider_id)
        if version < 1 or version > 3:
            raise ValidationError("QUOTATION_VERSION_OUT_OF_RANGE: La versión debe estar entre 1 y 3.")
        _field_clean(
            Cotizacion,
            {
                "ronda_id": round_id,
                "proveedor_id": provider_id,
                "version": version,
                "monto": amount,
                "vigente": current,
                "estado": state,
                "fecha_cotizacion": quote_date,
                "observaciones": notes,
            },
            excluded=("ronda", "proveedor"),
        )
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("START TRANSACTION")
                if self._round(cursor, round_id, lock=True) is None:
                    raise QuotationNotFound("La ronda no existe en BASE_TAREAS.")
                cursor.execute(
                    "SELECT version FROM tareas_cotizacion "
                    "WHERE ronda_id=%s AND proveedor_id=%s FOR UPDATE",
                    (round_id, provider_id),
                )
                versions = {row[0] for row in cursor.fetchall()}
                if version in versions:
                    raise ValidationError(
                        "QUOTATION_VERSION_DUPLICATE: La versión ya existe para este proveedor y ronda."
                    )
                if len(versions) >= 3:
                    raise ValidationError(
                        "QUOTATION_VERSION_LIMIT: El proveedor ya tiene tres versiones en esta ronda."
                    )
                cursor.execute(
                    "INSERT INTO tareas_cotizacion "
                    "(ronda_id,proveedor_id,version,monto,vigente,estado,fecha_cotizacion,observaciones) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        round_id, provider_id, version, amount, bool(current),
                        state, quote_date, notes,
                    ),
                )
                result = self._quotation(cursor, cursor.lastrowid)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def update_quotation_status(self, *, quotation_id, state, round_id=None):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("START TRANSACTION")
                quotation = self._quotation(cursor, quotation_id, round_id, lock=True)
                if quotation is None:
                    raise QuotationNotFound("La cotización no existe en BASE_TAREAS.")
                clean = {
                    "ronda_id": quotation.round_id,
                    "proveedor_id": quotation.provider_id,
                    "version": quotation.version,
                    "monto": quotation.amount,
                    "vigente": quotation.current,
                    "estado": state,
                    "fecha_cotizacion": quotation.quote_date,
                    "observaciones": quotation.notes,
                }
                _field_clean(Cotizacion, clean, excluded=("ronda", "proveedor"))
                cursor.execute(
                    "UPDATE tareas_cotizacion SET estado=%s WHERE id=%s AND ronda_id=%s",
                    (state, quotation_id, quotation.round_id),
                )
                result = self._quotation(cursor, quotation_id, quotation.round_id)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def add_quotation_document(
        self, *, quotation_id, format, user_id, uploaded_file=None, url="", created_at=None,
    ):
        _user_id(user_id)
        uploaded_file = optimize_uploaded_image(uploaded_file, format)
        document = DocumentoCotizacion(
            cotizacion_id=quotation_id,
            formato_archivo=format,
            archivo=getattr(uploaded_file, "name", "") if uploaded_file else "",
            url=url or "",
            usuario_id=user_id,
        )
        if created_at is not None:
            document.fecha = created_at
        document.full_clean(
            exclude=["cotizacion", "usuario"],
            validate_unique=False,
            validate_constraints=False,
        )
        filename = ""
        if uploaded_file:
            filename = default_storage.save(
                f"tareas/cotizaciones/{getattr(uploaded_file, 'name', 'archivo')}",
                uploaded_file,
            )
        try:
            with self._connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    if self._quotation(cursor, quotation_id) is None:
                        raise QuotationNotFound("La cotización no existe en BASE_TAREAS.")
                    created = created_at or timezone.now()
                    cursor.execute(
                        "INSERT INTO tareas_documentocotizacion "
                        "(cotizacion_id,formato_archivo,archivo,url,usuario_id,fecha) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (quotation_id, format, filename, url or "", user_id, created),
                    )
                    result = self._document(cursor, cursor.lastrowid)
                    connection.commit()
                    return result
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except Exception:
            if filename:
                default_storage.delete(filename)
            raise


def resolve_quotation_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            alias = context.django_alias
            if not alias or alias not in settings.DATABASES:
                raise QuotationStorageError("El alias Django de BASE_TAREAS no está disponible.")
            return DjangoQuotationStorage(alias)
        if context.backend_type == "MYSQL_CONFIG":
            config = context.mysql_connection
            database_name = context.database_name
            if not database_name:
                raise QuotationStorageError("La base de BASE_TAREAS no está configurada.")
            return MySQLQuotationStorage(config, database_name)
        raise QuotationStorageError("El backend configurado de BASE_TAREAS no es compatible.")
    except QuotationStorageError:
        raise
    except (TareaConnectionError, ObjectDoesNotExist, KeyError, TypeError, ValueError) as exc:
        logger.error("Quotation BASE_TAREAS resolution failed.")
        raise QuotationStorageError(
            "No se pudo resolver el almacenamiento de cotizaciones."
        ) from exc
    except Exception as exc:
        logger.error("Quotation BASE_TAREAS resolution failed.")
        raise QuotationStorageError(
            "No se pudo resolver el almacenamiento de cotizaciones."
        ) from exc


def execute_storage(storage, operation, **kwargs):
    try:
        return getattr(storage, operation)(**kwargs)
    except (QuotationStorageError, ValidationError):
        raise
    except Exception as exc:
        logger.error("Quotation storage failed: operation=%s", operation)
        raise QuotationStorageError(
            "No se pudo completar la operación de cotizaciones."
        ) from exc
