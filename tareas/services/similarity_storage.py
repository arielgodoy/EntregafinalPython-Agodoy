"""Configured persistence for task similarity data stored with BASE_TAREAS."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.models import Empresa
from settings.services.mysql_connections import open_mysql_connection
from tareas.models import EvaluacionSimilitud, Tarea, UmbralSimilitudEmpresa
from tareas.services.connection_roles import (
    TareaConnectionError,
    resolve_operational_backend,
)


class SimilarityStorageError(ValidationError):
    """A controlled failure while resolving or accessing similarity storage."""


def _mark_persisted(instance):
    instance._state.adding = False
    return instance


def _as_datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _task_instance(row):
    return _mark_persisted(
        Tarea(
            pk=row[0],
            empresa_id=row[1],
            correlativo=row[2],
            titulo=row[3],
            descripcion=row[4],
            prioridad=row[5],
            estado=row[6],
            anulada=bool(row[7]),
            tipo_ambito=row[8],
            local_id=row[9],
            departamento_id=row[10],
            todo_origen_id=row[11],
            tarea_origen_id=row[12],
        )
    )


def _evaluation_instance(row, task, candidate):
    evaluation = _mark_persisted(
        EvaluacionSimilitud(
            pk=row[0],
            tarea_id=row[1],
            tarea_candidata_id=row[2],
            porcentaje=Decimal(str(row[3])),
            umbral_aplicado=Decimal(str(row[4])),
            supera_umbral=bool(row[5]),
            decision=row[6],
            confirmada_por_id=row[7],
            confirmada_at=_as_datetime(row[8]),
            created_at=_as_datetime(row[9]),
        )
    )
    evaluation.tarea = task
    evaluation.tarea_candidata = candidate
    return evaluation


def _validate_threshold_references(configuration):
    try:
        Empresa.objects.using("default").only("pk").get(pk=configuration.empresa_id)
        User.objects.using("default").only("pk").get(pk=configuration.actualizado_por_id)
    except (Empresa.DoesNotExist, User.DoesNotExist) as exc:
        raise ValidationError("La Empresa o el usuario indicado no existe.") from exc


def _validate_evaluation_actor(evaluation):
    if evaluation.confirmada_por_id is None:
        return
    try:
        User.objects.using("default").only("pk").get(pk=evaluation.confirmada_por_id)
    except User.DoesNotExist as exc:
        raise ValidationError("El usuario de confirmación no existe.") from exc


class DjangoSimilarityUnit:
    def __init__(self, alias):
        self.alias = alias

    def get_threshold(self, company_id):
        return (
            UmbralSimilitudEmpresa.objects.using(self.alias)
            .filter(empresa_id=company_id)
            .first()
        )

    def save_threshold(self, configuration):
        _validate_threshold_references(configuration)
        configuration.full_clean(
            exclude=["empresa", "actualizado_por"],
            validate_unique=False,
            validate_constraints=False,
        )
        configuration.save(using=self.alias)
        return configuration

    def get_task(self, task_id, company_id=None, *, lock=False):
        queryset = Tarea.objects.using(self.alias)
        if lock:
            queryset = queryset.select_for_update()
        filters = {"pk": task_id}
        if company_id is not None:
            filters["empresa_id"] = company_id
        try:
            return queryset.get(**filters)
        except Tarea.DoesNotExist as exc:
            raise SimilarityStorageError(
                "La tarea no existe en BASE_TAREAS."
            ) from exc

    def candidate_tasks(self, task, states):
        return list(
            Tarea.objects.using(self.alias)
            .filter(
                empresa_id=task.empresa_id,
                estado__in=states,
                anulada=False,
            )
            .exclude(pk=task.pk)
            .order_by("pk")
        )

    def get_evaluation_for_pair(self, task_id, candidate_id, task, candidate):
        evaluation = (
            EvaluacionSimilitud.objects.using(self.alias)
            .filter(tarea_id=task_id, tarea_candidata_id=candidate_id)
            .first()
        )
        if evaluation is not None:
            evaluation.tarea = task
            evaluation.tarea_candidata = candidate
        return evaluation

    def get_evaluation(self, evaluation_id):
        try:
            return (
                EvaluacionSimilitud.objects.using(self.alias)
                .select_related("tarea", "tarea_candidata")
                .get(pk=evaluation_id)
            )
        except EvaluacionSimilitud.DoesNotExist as exc:
            raise SimilarityStorageError(
                "La evaluación no existe en BASE_TAREAS."
            ) from exc

    def save_evaluation(self, evaluation, update_fields=None):
        _validate_evaluation_actor(evaluation)
        evaluation.full_clean(
            exclude=["tarea", "tarea_candidata", "confirmada_por"],
            validate_unique=False,
            validate_constraints=False,
        )
        if update_fields is None:
            evaluation.save(using=self.alias)
        else:
            evaluation.save(using=self.alias, update_fields=update_fields)
        return evaluation

    def list_evaluations(self, task_id):
        return list(
            EvaluacionSimilitud.objects.using(self.alias)
            .filter(tarea_id=task_id)
            .select_related("tarea_candidata")
            .order_by("-porcentaje", "tarea_candidata_id")
        )

    def has_confirmed_origin(self, task_id, evaluation_id):
        return (
            EvaluacionSimilitud.objects.using(self.alias)
            .filter(
                tarea_id=task_id,
                decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA,
            )
            .exclude(pk=evaluation_id)
            .exists()
        )

    def save_task_origin(self, task, candidate):
        task.tarea_origen_id = candidate.pk
        task.save(using=self.alias, update_fields=["tarea_origen"])


class DjangoSimilarityStorage:
    def __init__(self, alias):
        self.alias = alias

    @contextmanager
    def atomic(self):
        with transaction.atomic(using=self.alias):
            yield DjangoSimilarityUnit(self.alias)


class MySQLSimilarityUnit:
    def __init__(self, cursor):
        self.cursor = cursor

    def get_threshold(self, company_id):
        self.cursor.execute(
            "SELECT id,empresa_id,porcentaje,actualizado_por_id,actualizado_at "
            "FROM tareas_umbralsimilitudempresa WHERE empresa_id=%s",
            (company_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return _mark_persisted(
            UmbralSimilitudEmpresa(
                pk=row[0],
                empresa_id=row[1],
                porcentaje=Decimal(str(row[2])),
                actualizado_por_id=row[3],
                actualizado_at=_as_datetime(row[4]),
            )
        )

    def save_threshold(self, configuration):
        _validate_threshold_references(configuration)
        configuration.full_clean(
            exclude=["empresa", "actualizado_por"],
            validate_unique=False,
            validate_constraints=False,
        )
        now = timezone.now()
        configuration.actualizado_at = now
        if configuration.pk:
            self.cursor.execute(
                "UPDATE tareas_umbralsimilitudempresa "
                "SET porcentaje=%s,actualizado_por_id=%s,actualizado_at=%s WHERE id=%s",
                (
                    configuration.porcentaje,
                    configuration.actualizado_por_id,
                    now,
                    configuration.pk,
                ),
            )
        else:
            self.cursor.execute(
                "INSERT INTO tareas_umbralsimilitudempresa "
                "(empresa_id,porcentaje,actualizado_por_id,actualizado_at) "
                "VALUES (%s,%s,%s,%s)",
                (
                    configuration.empresa_id,
                    configuration.porcentaje,
                    configuration.actualizado_por_id,
                    now,
                ),
            )
            configuration.pk = self.cursor.lastrowid
            configuration._state.adding = False
        return configuration

    def get_task(self, task_id, company_id=None, *, lock=False):
        sql = (
            "SELECT id,empresa_id,correlativo,titulo,descripcion,prioridad,estado,"
            "anulada,tipo_ambito,local_id,departamento_id,todo_origen_id,tarea_origen_id "
            "FROM tareas_tarea WHERE id=%s"
        )
        params = [task_id]
        if company_id is not None:
            sql += " AND empresa_id=%s"
            params.append(company_id)
        if lock:
            sql += " FOR UPDATE"
        self.cursor.execute(sql, tuple(params))
        row = self.cursor.fetchone()
        if row is None:
            raise SimilarityStorageError("La tarea no existe en BASE_TAREAS.")
        return _task_instance(row)

    def candidate_tasks(self, task, states):
        states = tuple(states)
        placeholders = ",".join("%s" for _ in states)
        self.cursor.execute(
            "SELECT id,empresa_id,correlativo,titulo,descripcion,prioridad,estado,"
            "anulada,tipo_ambito,local_id,departamento_id,todo_origen_id,tarea_origen_id "
            f"FROM tareas_tarea WHERE empresa_id=%s AND estado IN ({placeholders}) "
            "AND anulada=0 AND id<>%s ORDER BY id",
            (task.empresa_id, *states, task.pk),
        )
        return [_task_instance(row) for row in self.cursor.fetchall()]

    def get_evaluation_for_pair(self, task_id, candidate_id, task, candidate):
        self.cursor.execute(
            "SELECT id,tarea_id,tarea_candidata_id,porcentaje,umbral_aplicado,"
            "supera_umbral,decision,confirmada_por_id,confirmada_at,created_at "
            "FROM tareas_evaluacionsimilitud WHERE tarea_id=%s AND tarea_candidata_id=%s",
            (task_id, candidate_id),
        )
        row = self.cursor.fetchone()
        return _evaluation_instance(row, task, candidate) if row else None

    def get_evaluation(self, evaluation_id):
        self.cursor.execute(
            "SELECT id,tarea_id,tarea_candidata_id,porcentaje,umbral_aplicado,"
            "supera_umbral,decision,confirmada_por_id,confirmada_at,created_at "
            "FROM tareas_evaluacionsimilitud WHERE id=%s",
            (evaluation_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise SimilarityStorageError("La evaluación no existe en BASE_TAREAS.")
        task = self.get_task(row[1])
        candidate = self.get_task(row[2])
        return _evaluation_instance(row, task, candidate)

    def save_evaluation(self, evaluation, update_fields=None):
        _validate_evaluation_actor(evaluation)
        evaluation.full_clean(
            exclude=["tarea", "tarea_candidata", "confirmada_por"],
            validate_unique=False,
            validate_constraints=False,
        )
        if evaluation.pk:
            if update_fields and set(update_fields) == {
                "decision", "confirmada_por", "confirmada_at"
            }:
                self.cursor.execute(
                    "UPDATE tareas_evaluacionsimilitud SET decision=%s,"
                    "confirmada_por_id=%s,confirmada_at=%s WHERE id=%s",
                    (
                        evaluation.decision,
                        evaluation.confirmada_por_id,
                        evaluation.confirmada_at,
                        evaluation.pk,
                    ),
                )
            else:
                self.cursor.execute(
                    "UPDATE tareas_evaluacionsimilitud SET porcentaje=%s,"
                    "umbral_aplicado=%s,supera_umbral=%s WHERE id=%s",
                    (
                        evaluation.porcentaje,
                        evaluation.umbral_aplicado,
                        evaluation.supera_umbral,
                        evaluation.pk,
                    ),
                )
        else:
            evaluation.created_at = evaluation.created_at or timezone.now()
            self.cursor.execute(
                "INSERT INTO tareas_evaluacionsimilitud "
                "(tarea_id,tarea_candidata_id,porcentaje,umbral_aplicado,"
                "supera_umbral,decision,confirmada_por_id,confirmada_at,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    evaluation.tarea_id,
                    evaluation.tarea_candidata_id,
                    evaluation.porcentaje,
                    evaluation.umbral_aplicado,
                    evaluation.supera_umbral,
                    evaluation.decision,
                    evaluation.confirmada_por_id,
                    evaluation.confirmada_at,
                    evaluation.created_at,
                ),
            )
            evaluation.pk = self.cursor.lastrowid
            evaluation._state.adding = False
        return evaluation

    def list_evaluations(self, task_id):
        self.cursor.execute(
            "SELECT id,tarea_id,tarea_candidata_id,porcentaje,umbral_aplicado,"
            "supera_umbral,decision,confirmada_por_id,confirmada_at,created_at "
            "FROM tareas_evaluacionsimilitud WHERE tarea_id=%s "
            "ORDER BY porcentaje DESC,tarea_candidata_id",
            (task_id,),
        )
        evaluations = []
        for row in self.cursor.fetchall():
            task = self.get_task(row[1])
            candidate = self.get_task(row[2])
            evaluations.append(_evaluation_instance(row, task, candidate))
        return evaluations

    def has_confirmed_origin(self, task_id, evaluation_id):
        self.cursor.execute(
            "SELECT 1 FROM tareas_evaluacionsimilitud "
            "WHERE tarea_id=%s AND decision=%s AND id<>%s LIMIT 1",
            (
                task_id,
                EvaluacionSimilitud.Decision.MISMO_PROBLEMA,
                evaluation_id,
            ),
        )
        return self.cursor.fetchone() is not None

    def save_task_origin(self, task, candidate):
        self.cursor.execute(
            "UPDATE tareas_tarea SET tarea_origen_id=%s WHERE id=%s",
            (candidate.pk, task.pk),
        )
        task.tarea_origen_id = candidate.pk


class MySQLSimilarityStorage:
    def __init__(self, connection_config, database_name):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def atomic(self):
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                if callable(getattr(connection, "begin", None)):
                    connection.begin()
                yield MySQLSimilarityUnit(cursor)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()


def resolve_similarity_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            alias = context.django_alias
            if not alias or alias not in settings.DATABASES:
                raise SimilarityStorageError(
                    "El alias Django de BASE_TAREAS no está disponible."
                )
            return DjangoSimilarityStorage(alias)
        if context.backend_type == "MYSQL_CONFIG":
            return MySQLSimilarityStorage(context.mysql_connection, context.database_name)
        raise SimilarityStorageError(
            "El tipo de almacenamiento de BASE_TAREAS no está soportado."
        )
    except TareaConnectionError as exc:
        raise SimilarityStorageError(
            "No se pudo resolver el almacenamiento configurado de Similarity."
        ) from exc
