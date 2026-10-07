"""ID-based Hito/Avance aggregate; operational data never falls back to SYSTEM."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import logging
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa, user_has_permission_for_empresa,
)
from settings.services.mysql_connections import open_mysql_connection
from tareas.models import (
    Avance, Hito, HitoEvidencia, HitoHistorial, Tarea, TareaParticipante,
)
from .connection_roles import resolve_operational_backend
from .image_processing import optimize_uploaded_image
from .progress_storage import (
    calculate_weighted_progress, progress_percentage, refresh_weighted_progress,
)
from .task_storage import TaskStorageError

logger = logging.getLogger(__name__)
ERROR_KEY = "tareas.messages.generic_error"
MUTABLE_STATES = frozenset({"BORRADOR", "ACTIVA", "GESTION"})
PUBLISHED_STATES = ("ACTIVA", "GESTION", "PENDIENTE_APROBACION_CIERRE", "CERRADA")


class MilestoneNotFound(Exception):
    pass


@dataclass(frozen=True)
class CreateMilestoneCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    nombre: str
    responsable_id: int
    cumplimiento: object = 0
    peso: object = 1


@dataclass(frozen=True)
class UpdateMilestoneCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    milestone_id: int
    nombre: str | None = None
    cumplimiento: object = None
    peso: object = None


@dataclass(frozen=True)
class CompleteMilestoneCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    milestone_id: int
    resena_cierre: str
    formato_archivo: str
    archivo: object = None
    url: str = ""


@dataclass(frozen=True)
class ReassignMilestoneCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    milestone_id: int
    responsable_id: int
    motivo: str


@dataclass(frozen=True)
class SetMilestoneAnnulledCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    milestone_id: int
    anulado: bool


@dataclass(frozen=True)
class DeleteMilestoneCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    milestone_id: int


@dataclass(frozen=True)
class UpdateManualProgressCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    porcentaje: object


@dataclass(frozen=True)
class SetWeightedProgressModeCommand:
    task_id: int
    empresa_id: int
    actor_id: int


COMMAND_TYPES = (
    CreateMilestoneCommand, UpdateMilestoneCommand, CompleteMilestoneCommand,
    ReassignMilestoneCommand, SetMilestoneAnnulledCommand, DeleteMilestoneCommand,
    UpdateManualProgressCommand, SetWeightedProgressModeCommand,
)


@dataclass(frozen=True)
class MilestoneResult:
    task_id: int
    milestone_id: int | None
    changed: bool = True
    deleted: bool = False


@dataclass(frozen=True)
class MilestoneHistoryDTO:
    id: int
    tipo_evento: str
    usuario_id: int | None
    usuario_username: str
    fecha: object
    datos_anteriores: dict
    datos_nuevos: dict
    motivo: str


@dataclass(frozen=True)
class AssignedTaskDTO:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    prioridad: str
    estado: str
    responsable_id: int | None

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class AssignedMilestoneDTO:
    id: int
    nombre: str
    cumplimiento: Decimal
    peso: Decimal
    completado: bool
    anulado: bool
    responsable_id: int
    tarea: AssignedTaskDTO
    writable: bool

    @property
    def pk(self):
        return self.id


def _invalid():
    raise ValidationError(ERROR_KEY)


def _identity(empresa_id, actor_id, action, vista="Tareas - Hitos"):
    try:
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        actor = User.objects.using("default").get(pk=actor_id, is_active=True)
        if not (
            get_valid_users_for_empresa(empresa, active_only=True).using("default")
            .filter(pk=actor.pk).exists()
            and user_has_permission_for_empresa(
                user=actor, empresa=empresa, vista_nombre=vista, accion=action,
            )
        ):
            raise PermissionDenied
    except (Empresa.DoesNotExist, User.DoesNotExist):
        raise PermissionDenied from None
    except DatabaseError:
        logger.error("Hito SYSTEM authorization unavailable")
        raise TaskStorageError(ERROR_KEY) from None
    return empresa, actor


def _eligible(empresa, user_id):
    if type(user_id) is not int or not get_valid_users_for_empresa(
        empresa, active_only=True,
    ).using("default").filter(pk=user_id, is_active=True).exists():
        _invalid()


def _manager(adapter, task, empresa, actor):
    return bool(
        actor.pk in {task.creada_por_id, task.responsable_id}
        or adapter.manager_role(task.pk, actor.pk)
        or any(user_has_permission_for_empresa(
            user=actor, empresa=empresa, vista_nombre="Tareas - Hitos", accion=flag,
        ) for flag in ("supervisor", "autorizar"))
    )


def _milestone_values(nombre, cumplimiento, peso):
    try:
        name = Hito._meta.get_field("nombre").clean(str(nombre or "").strip(), None)
        percentage = progress_percentage(cumplimiento)
        weight = Hito._meta.get_field("peso").clean(peso, None)
        if not weight.is_finite() or weight <= 0:
            _invalid()
        return dict(nombre=name, cumplimiento=percentage, peso=weight)
    except (TypeError, ValueError, ValidationError):
        _invalid()


def _history(adapter, hito_id, event, actor_id, before, after, reason=""):
    adapter.insert(HitoHistorial, dict(
        hito_id=hito_id, tipo_evento=event, usuario_id=actor_id, fecha=timezone.now(),
        datos_anteriores=before, datos_nuevos=after, motivo=reason,
    ))


def _annul(adapter, hito, command, annulled):
    if bool(hito.anulado) == annulled:
        return MilestoneResult(command.task_id, hito.pk, changed=False)
    adapter.update_hito(hito.pk, command.task_id, {"anulado": annulled})
    _history(
        adapter, hito.pk, "ANULACION" if annulled else "REACTIVACION", command.actor_id,
        {"anulado": bool(hito.anulado)}, {"anulado": annulled},
    )
    refresh_weighted_progress(adapter, command.task_id)
    return MilestoneResult(command.task_id, hito.pk)


def _complete(adapter, hito, command, saved_files):
    if hito.anulado or hito.completado:
        _invalid()
    review = str(command.resena_cierre or "").strip()
    if not review:
        _invalid()
    evidence = HitoEvidencia(
        hito_id=hito.pk, usuario_id=command.actor_id,
        formato_archivo=command.formato_archivo,
        archivo=optimize_uploaded_image(command.archivo, command.formato_archivo) or "",
        url=command.url or "", fecha=timezone.now(),
    )
    evidence.full_clean(
        exclude=["hito", "usuario"], validate_unique=False, validate_constraints=False,
    )
    if evidence.archivo and not evidence.archivo._committed:
        evidence.archivo.save(evidence.archivo.name, evidence.archivo.file, save=False)
        saved_files.append((evidence.archivo.storage, evidence.archivo.name))
    evidence_id = adapter.insert(HitoEvidencia, dict(
        hito_id=hito.pk, usuario_id=command.actor_id,
        formato_archivo=evidence.formato_archivo, archivo=evidence.archivo.name or "",
        url=evidence.url, fecha=evidence.fecha,
    ))
    now = timezone.now()
    adapter.update_hito(hito.pk, command.task_id, dict(
        completado=True, cumplimiento=Decimal("100"), completado_por_id=command.actor_id,
        fecha_completado=now, resena_cierre=review,
    ))
    _history(adapter, hito.pk, "COMPLETADO", command.actor_id,
             {"completado": False, "cumplimiento": str(hito.cumplimiento)}, dict(
                 completado=True, cumplimiento="100", responsable=hito.responsable_id,
                 completado_por=command.actor_id, fecha_completado=now.isoformat(),
                 resena_cierre=review, evidencia_id=evidence_id,
             ), review)
    refresh_weighted_progress(adapter, command.task_id)
    return MilestoneResult(command.task_id, hito.pk)


def _mutate(adapter, command, saved_files):
    if not isinstance(command, COMMAND_TYPES):
        _invalid()
    action = (
        "crear" if isinstance(command, CreateMilestoneCommand)
        else "eliminar" if isinstance(command, DeleteMilestoneCommand) else "modificar"
    )
    empresa, actor = _identity(command.empresa_id, command.actor_id, action)
    task = adapter.task(command.task_id, command.empresa_id)
    if task.estado not in MUTABLE_STATES or adapter.annulled(task, command.empresa_id):
        _invalid()
    if isinstance(command, (UpdateManualProgressCommand, SetWeightedProgressModeCommand)):
        progress = adapter.progress(task.pk)
        if isinstance(command, UpdateManualProgressCommand):
            percentage = progress_percentage(command.porcentaje)
            if progress is not None and progress.modo == Avance.Modo.PONDERADO:
                _invalid()
            mode = Avance.Modo.MANUAL
        else:
            mode = Avance.Modo.PONDERADO
            percentage = calculate_weighted_progress(adapter.milestones(task.pk))
        adapter.save_progress(task.pk, mode, percentage)
        return MilestoneResult(task.pk, None)
    manager = _manager(adapter, task, empresa, actor)
    if isinstance(command, CreateMilestoneCommand):
        if not manager:
            raise PermissionDenied
        _eligible(empresa, command.responsable_id)
        values = _milestone_values(command.nombre, command.cumplimiento, command.peso)
        hito_id = adapter.insert(Hito, dict(
            tarea_id=task.pk, responsable_id=command.responsable_id, anulado=False,
            completado=False, completado_por_id=None, fecha_completado=None,
            resena_cierre="", fecha_creacion=timezone.now(), **values,
        ))
        _history(adapter, hito_id, "CREACION", actor.pk, {}, dict(
            nombre=values["nombre"], cumplimiento=str(values["cumplimiento"]),
            peso=str(values["peso"]), responsable=command.responsable_id,
        ))
        refresh_weighted_progress(adapter, task.pk)
        return MilestoneResult(task.pk, hito_id)
    hito = adapter.hito(command.milestone_id, task.pk)
    if not manager and not (
        isinstance(command, (UpdateMilestoneCommand, CompleteMilestoneCommand))
        and hito.responsable_id == actor.pk
    ):
        raise PermissionDenied
    if isinstance(command, SetMilestoneAnnulledCommand):
        if type(command.anulado) is not bool:
            _invalid()
        return _annul(adapter, hito, command, command.anulado)
    if isinstance(command, DeleteMilestoneCommand):
        events = adapter.history_rows(hito.pk)
        clean = len(events) == 1 and events[0]["tipo_evento"] == "CREACION"
        if not clean or hito.completado or adapter.has_evidence(hito.pk):
            return _annul(adapter, hito, command, True)
        adapter.delete_hito(hito.pk, task.pk)
        refresh_weighted_progress(adapter, task.pk)
        return MilestoneResult(task.pk, hito.pk, deleted=True)
    if hito.completado or hito.anulado:
        _invalid()
    if isinstance(command, CompleteMilestoneCommand):
        _eligible(empresa, hito.responsable_id)
        return _complete(adapter, hito, command, saved_files)
    if isinstance(command, ReassignMilestoneCommand):
        reason = str(command.motivo or "").strip()
        if not reason or command.responsable_id == hito.responsable_id:
            _invalid()
        _eligible(empresa, command.responsable_id)
        adapter.update_hito(hito.pk, task.pk, {"responsable_id": command.responsable_id})
        _history(adapter, hito.pk, "REASIGNACION", actor.pk,
                 {"responsable": hito.responsable_id}, {"responsable": command.responsable_id}, reason)
        return MilestoneResult(task.pk, hito.pk)
    requested = _milestone_values(
        hito.nombre if command.nombre is None else command.nombre,
        hito.cumplimiento if command.cumplimiento is None else command.cumplimiento,
        hito.peso if command.peso is None else command.peso,
    )
    if not manager and any(requested[key] != getattr(hito, key) for key in ("nombre", "peso")):
        raise PermissionDenied
    changes = {key: value for key, value in requested.items() if value != getattr(hito, key)}
    if not changes:
        return MilestoneResult(task.pk, hito.pk, changed=False)
    _eligible(empresa, hito.responsable_id)
    adapter.update_hito(hito.pk, task.pk, changes)
    for key, value in changes.items():
        _history(adapter, hito.pk, {
            "nombre": "CAMBIO_NOMBRE", "cumplimiento": "CAMBIO_CUMPLIMIENTO", "peso": "CAMBIO_PESO",
        }[key], actor.pk, {key: str(getattr(hito, key))}, {key: str(value)})
    refresh_weighted_progress(adapter, task.pk)
    return MilestoneResult(task.pk, hito.pk)


def _failed_files(files, commit_attempted):
    if commit_attempted:
        if files:
            logger.error("Hito commit outcome uncertain; retaining new files for reconciliation")
        return
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:
            logger.error("Hito new-file cleanup failed")


class _Queries:
    def detail(self, *, task_id, empresa_id, actor_id):
        from .detail_storage import DetailTaskNotFound, TaskDetailSections
        _identity(empresa_id, actor_id, "ingresar")
        try:
            return self._detail_storage().get_task_detail(
                task_id=task_id, empresa_id=empresa_id,
                sections=TaskDetailSections(
                    milestones=True, mini_tasks=False, links=False, documents=False,
                ),
            )
        except DetailTaskNotFound:
            raise MilestoneNotFound from None
        except TaskStorageError:
            raise
        except Exception:
            logger.error("Hito detail failed: task=%s company=%s", task_id, empresa_id)
            raise TaskStorageError(ERROR_KEY) from None

    def history(self, *, task_id, empresa_id, actor_id, milestone_id):
        _identity(empresa_id, actor_id, "ingresar")
        rows = self._read(lambda adapter: (
            adapter.task(task_id, empresa_id), adapter.hito(milestone_id, task_id),
            adapter.history_rows(milestone_id),
        )[2])
        try:
            users = User.objects.using("default").in_bulk({row["usuario_id"] for row in rows})
        except DatabaseError:
            logger.error("Hito history SYSTEM identities unavailable")
            raise TaskStorageError(ERROR_KEY) from None
        return tuple(MilestoneHistoryDTO(
            usuario_username=users[row["usuario_id"]].username
            if row["usuario_id"] in users else "", **row,
        ) for row in rows)

    def weighted(self, *, task_id, empresa_id):
        return self._read(lambda adapter: (
            adapter.task(task_id, empresa_id),
            calculate_weighted_progress(adapter.milestones(task_id)),
        )[1])

    def latest_movement(self, *, task_id, empresa_id):
        return self._read(lambda adapter: (
            adapter.task(task_id, empresa_id), adapter.latest_movement(task_id),
        )[1])

    def assigned(self, *, empresa_id, actor_id):
        _identity(empresa_id, actor_id, "ingresar", "Tareas - Dashboard personal")
        def read(adapter):
            items = []
            for row in adapter.assigned_rows(empresa_id, actor_id):
                task = SimpleNamespace(
                    pk=row["task_id"], empresa_id=empresa_id, anulada=row["task_anulada"],
                )
                if adapter.annulled(task, empresa_id):
                    continue
                items.append(AssignedMilestoneDTO(
                    id=row["id"], nombre=row["nombre"],
                    cumplimiento=Decimal(str(row["cumplimiento"])), peso=Decimal(str(row["peso"])),
                    completado=bool(row["completado"]), anulado=False, responsable_id=actor_id,
                    tarea=AssignedTaskDTO(
                        id=row["task_id"], empresa_id=empresa_id, correlativo=row["correlativo"],
                        titulo=row["titulo"], prioridad=row["prioridad"], estado=row["estado"],
                        responsable_id=row["responsable_id"],
                    ), writable=row["estado"] in MUTABLE_STATES and not row["completado"],
                ))
            return tuple(items)
        return self._read(read)


class DjangoMilestoneStorage(_Queries):
    def __init__(self, alias):
        self.alias = alias

    def _detail_storage(self):
        from .detail_storage import DjangoTaskDetailStorage
        return DjangoTaskDetailStorage(self.alias)

    def execute(self, command):
        files = []
        commit_attempted = False
        try:
            with transaction.atomic(using=self.alias):
                result = _mutate(_DjangoAdapter(self.alias, lock=True), command, files)
                commit_attempted = True
            return result
        except (MilestoneNotFound, PermissionDenied, ValidationError):
            _failed_files(files, commit_attempted)
            raise
        except Exception:
            _failed_files(files, commit_attempted)
            logger.error("Hito storage failed: task=%s company=%s", command.task_id, command.empresa_id)
            raise TaskStorageError(ERROR_KEY) from None

    def _read(self, callback):
        try:
            return callback(_DjangoAdapter(self.alias))
        except (MilestoneNotFound, PermissionDenied, ValidationError):
            raise
        except Exception:
            logger.error("Hito read failed")
            raise TaskStorageError(ERROR_KEY) from None


class _DjangoAdapter:
    def __init__(self, alias, lock=False):
        self.alias = alias
        self.lock = lock

    def query(self, model):
        qs = model.objects.using(self.alias)
        return qs.select_for_update() if self.lock else qs

    def task(self, task_id, empresa_id):
        try:
            return self.query(Tarea).get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist:
            raise MilestoneNotFound from None

    def hito(self, hito_id, task_id):
        try:
            return self.query(Hito).get(pk=hito_id, tarea_id=task_id)
        except Hito.DoesNotExist:
            raise MilestoneNotFound from None

    def annulled(self, task, empresa_id):
        from tareas.models import TareaRelacion
        annulled = bool(task.anulada)
        current_id = task.pk
        for _ in range(2):
            parent_id = self.query(TareaRelacion).filter(
                hija_id=current_id, padre__empresa_id=empresa_id, hija__empresa_id=empresa_id,
            ).values_list("padre_id", flat=True).first()
            if parent_id is None:
                break
            parent = self.task(parent_id, empresa_id)
            annulled = annulled or parent.anulada
            current_id = parent.pk
        return annulled

    def manager_role(self, task_id, actor_id):
        return self.query(TareaParticipante).filter(
            tarea_id=task_id, usuario_id=actor_id,
            rol__in=["RESPONSABLE_LIDER", "SUPERVISOR", "AUTORIZADOR"],
        ).exists()

    def insert(self, model, values):
        row = model(**values)
        model.objects.using(self.alias).bulk_create([row])
        return row.pk

    def update_hito(self, hito_id, task_id, values):
        Hito.objects.using(self.alias).filter(pk=hito_id, tarea_id=task_id).update(**values)

    def milestones(self, task_id):
        return list(self.query(Hito).filter(tarea_id=task_id).order_by("pk"))

    def progress(self, task_id):
        return self.query(Avance).filter(tarea_id=task_id).first()

    def save_progress(self, task_id, mode, percentage):
        existing = self.progress(task_id)
        if existing:
            Avance.objects.using(self.alias).filter(pk=existing.pk, tarea_id=task_id).update(
                modo=mode, porcentaje=percentage, fecha_actualizacion=timezone.now(),
            )
        else:
            self.insert(Avance, dict(
                tarea_id=task_id, modo=mode, porcentaje=percentage,
                fecha_actualizacion=timezone.now(),
            ))

    def history_rows(self, hito_id):
        return list(self.query(HitoHistorial).filter(hito_id=hito_id).order_by("fecha", "pk").values(
            "id", "tipo_evento", "usuario_id", "fecha", "datos_anteriores", "datos_nuevos", "motivo",
        ))

    def has_evidence(self, hito_id):
        return self.query(HitoEvidencia).filter(hito_id=hito_id).exists()

    def delete_hito(self, hito_id, task_id):
        HitoHistorial.objects.using(self.alias).filter(hito_id=hito_id).delete()
        Hito.objects.using(self.alias).filter(pk=hito_id, tarea_id=task_id).delete()

    def latest_movement(self, task_id):
        return self.query(HitoHistorial).filter(hito__tarea_id=task_id).order_by(
            "-fecha", "-pk",
        ).values_list("fecha", flat=True).first()

    def assigned_rows(self, empresa_id, actor_id):
        rows = self.query(Hito).filter(
            tarea__empresa_id=empresa_id, tarea__estado__in=PUBLISHED_STATES,
            responsable_id=actor_id, anulado=False,
        ).order_by("tarea__prioridad", "tarea_id", "fecha_creacion", "pk").values(
            "id", "nombre", "cumplimiento", "peso", "completado", "tarea_id",
            "tarea__anulada", "tarea__correlativo", "tarea__titulo", "tarea__prioridad",
            "tarea__estado", "tarea__responsable_id",
        )
        return [dict(
            id=row["id"], nombre=row["nombre"], cumplimiento=row["cumplimiento"], peso=row["peso"],
            completado=row["completado"], task_id=row["tarea_id"], task_anulada=row["tarea__anulada"],
            **{key: row["tarea__" + key] for key in (
                "correlativo", "titulo", "prioridad", "estado", "responsable_id",
            )},
        ) for row in rows]


class MySQLMilestoneStorage(_Queries):
    def __init__(self, config, database_name):
        self.connection_config = config
        self.database_name = database_name

    def _detail_storage(self):
        from .detail_storage import MySQLTaskDetailStorage
        return MySQLTaskDetailStorage(self.connection_config, self.database_name)

    def execute(self, command):
        files = []
        commit_attempted = False
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    result = _mutate(_MySQLAdapter(cursor, lock=True), command, files)
                    commit_attempted = True
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
            return result
        except (MilestoneNotFound, PermissionDenied, ValidationError):
            _failed_files(files, commit_attempted)
            raise
        except Exception:
            _failed_files(files, commit_attempted)
            logger.error("Hito MySQL storage failed: task=%s company=%s", command.task_id, command.empresa_id)
            raise TaskStorageError(ERROR_KEY) from None

    def _read(self, callback):
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    return callback(_MySQLAdapter(cursor))
                finally:
                    cursor.close()
        except (MilestoneNotFound, PermissionDenied, ValidationError):
            raise
        except Exception:
            logger.error("Hito MySQL read failed")
            raise TaskStorageError(ERROR_KEY) from None


class _MySQLAdapter:
    def __init__(self, cursor, lock=False):
        self.cursor = cursor
        self.suffix = " FOR UPDATE" if lock else ""

    def rows(self, sql, params=()):
        self.cursor.execute(sql, tuple(params))
        return [dict(zip((item[0] for item in self.cursor.description), row))
                for row in self.cursor.fetchall()]

    def task(self, task_id, empresa_id):
        rows = self.rows(
            "SELECT id, empresa_id, creada_por_id, responsable_id, estado, anulada "
            "FROM tareas_tarea WHERE id=%s AND empresa_id=%s" + self.suffix, (task_id, empresa_id),
        )
        if not rows:
            raise MilestoneNotFound
        return SimpleNamespace(pk=rows[0]["id"], **rows[0])

    def hito(self, hito_id, task_id):
        rows = self.rows(
            "SELECT id, nombre, responsable_id, anulado, completado, cumplimiento, peso "
            "FROM tareas_hito WHERE id=%s AND tarea_id=%s" + self.suffix, (hito_id, task_id),
        )
        if not rows:
            raise MilestoneNotFound
        return SimpleNamespace(pk=rows[0]["id"], **rows[0])

    def annulled(self, task, empresa_id):
        annulled = bool(task.anulada)
        current_id = task.pk
        for _ in range(2):
            rows = self.rows(
                "SELECT p.id, p.anulada FROM tareas_tarearelacion r "
                "JOIN tareas_tarea p ON p.id=r.padre_id JOIN tareas_tarea c ON c.id=r.hija_id "
                "WHERE r.hija_id=%s AND p.empresa_id=%s AND c.empresa_id=%s" + self.suffix,
                (current_id, empresa_id, empresa_id),
            )
            if not rows:
                break
            current_id = rows[0]["id"]
            annulled = annulled or bool(rows[0]["anulada"])
        return annulled

    def manager_role(self, task_id, actor_id):
        rows = self.rows(
            "SELECT rol FROM tareas_tareaparticipante WHERE tarea_id=%s AND usuario_id=%s"
            + self.suffix, (task_id, actor_id),
        )
        return any(row["rol"] in {"RESPONSABLE_LIDER", "SUPERVISOR", "AUTORIZADOR"} for row in rows)

    def insert(self, model, values):
        columns = ", ".join(values)
        marks = ", ".join("%s" for _ in values)
        self.cursor.execute(
            f"INSERT INTO {model._meta.db_table} ({columns}) VALUES ({marks})",
            tuple(json.dumps(value) if isinstance(value, dict) else value for value in values.values()),
        )
        return self.cursor.lastrowid

    def update_hito(self, hito_id, task_id, values):
        setters = ", ".join(f"{key}=%s" for key in values)
        self.cursor.execute(
            f"UPDATE tareas_hito SET {setters} WHERE id=%s AND tarea_id=%s",
            (*values.values(), hito_id, task_id),
        )

    def milestones(self, task_id):
        return [SimpleNamespace(**row) for row in self.rows(
            "SELECT cumplimiento, peso, anulado FROM tareas_hito WHERE tarea_id=%s ORDER BY id"
            + self.suffix, (task_id,),
        )]

    def progress(self, task_id):
        rows = self.rows("SELECT id, modo, porcentaje FROM tareas_avance WHERE tarea_id=%s"
                         + self.suffix, (task_id,))
        return SimpleNamespace(**rows[0]) if rows else None

    def save_progress(self, task_id, mode, percentage):
        if self.progress(task_id):
            self.cursor.execute(
                "UPDATE tareas_avance SET modo=%s, porcentaje=%s, fecha_actualizacion=%s WHERE tarea_id=%s",
                (mode, percentage, timezone.now(), task_id),
            )
        else:
            self.insert(Avance, dict(
                tarea_id=task_id, modo=mode, porcentaje=percentage,
                fecha_actualizacion=timezone.now(),
            ))

    def history_rows(self, hito_id):
        rows = self.rows(
            "SELECT id, tipo_evento, usuario_id, fecha, datos_anteriores, datos_nuevos, motivo "
            "FROM tareas_hitohistorial WHERE hito_id=%s ORDER BY fecha, id" + self.suffix, (hito_id,),
        )
        for row in rows:
            for key in ("datos_anteriores", "datos_nuevos"):
                if isinstance(row[key], str):
                    row[key] = json.loads(row[key])
        return rows

    def has_evidence(self, hito_id):
        return bool(self.rows("SELECT id FROM tareas_hitoevidencia WHERE hito_id=%s" + self.suffix,
                              (hito_id,)))

    def delete_hito(self, hito_id, task_id):
        self.cursor.execute("DELETE FROM tareas_hitohistorial WHERE hito_id=%s", (hito_id,))
        self.cursor.execute("DELETE FROM tareas_hito WHERE id=%s AND tarea_id=%s", (hito_id, task_id))

    def latest_movement(self, task_id):
        rows = self.rows(
            "SELECT hh.fecha FROM tareas_hitohistorial hh JOIN tareas_hito h ON h.id=hh.hito_id "
            "WHERE h.tarea_id=%s ORDER BY hh.fecha DESC, hh.id DESC LIMIT 1", (task_id,),
        )
        return rows[0]["fecha"] if rows else None

    def assigned_rows(self, empresa_id, actor_id):
        return self.rows(
            "SELECT h.id, h.nombre, h.cumplimiento, h.peso, h.completado, t.id AS task_id, "
            "t.anulada AS task_anulada, t.correlativo, t.titulo, t.prioridad, t.estado, t.responsable_id "
            "FROM tareas_hito h JOIN tareas_tarea t ON t.id=h.tarea_id "
            "WHERE h.responsable_id=%s AND t.empresa_id=%s AND h.anulado=0 "
            "AND t.estado IN (%s,%s,%s,%s) ORDER BY t.prioridad, t.id, h.fecha_creacion, h.id",
            (actor_id, empresa_id, *PUBLISHED_STATES),
        )


def resolve_milestone_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            return DjangoMilestoneStorage(context.django_alias)
        if context.backend_type == "MYSQL_CONFIG":
            return MySQLMilestoneStorage(context.mysql_connection, context.database_name)
    except Exception:
        logger.error("Hito BASE_TAREAS resolution failed")
        raise TaskStorageError(ERROR_KEY) from None
    logger.error("Unsupported Hito BASE_TAREAS source")
    raise TaskStorageError(ERROR_KEY)
