"""Backend-neutral storage for compound task assignment."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import Tarea, TareaReasignacion
from .connection_roles import TareaConnectionError, resolve_operational_backend
from .correlativos import reserve_next_number
from settings.services.mysql_connections import open_mysql_connection


@dataclass(frozen=True)
class AssignmentTask:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    descripcion: str
    prioridad: str
    responsable_id: int
    creada_por_id: int
    fecha_comun: object
    task: Tarea | None = None


class DjangoAssignmentStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def create(self, *, empresa_id, creador_id, assignments):
        created = []
        with transaction.atomic(using=self.alias):
            for assignment in assignments:
                number = reserve_next_number(empresa_id, using=self.alias)
                task = Tarea(
                    titulo=assignment["titulo"],
                    descripcion=assignment["descripcion"],
                    prioridad=assignment["prioridad"],
                    correlativo=f"B{number:07d}",
                    empresa_id=empresa_id,
                    creada_por_id=creador_id,
                    responsable_id=assignment["responsable_id"],
                )
                task.save(using=self.alias, force_insert=True)
                TareaReasignacion.objects.using(self.alias).create(
                    tarea_id=task.pk,
                    responsable_nuevo_id=assignment["responsable_id"],
                    usuario_id=creador_id,
                    fecha=assignment["fecha_comun"],
                    motivo=assignment["motivo"],
                )
                created.append(task)
        return tuple(
            AssignmentTask(
                id=task.pk,
                empresa_id=task.empresa_id,
                correlativo=task.correlativo,
                titulo=task.titulo,
                descripcion=task.descripcion,
                prioridad=task.prioridad,
                responsable_id=task.responsable_id,
                creada_por_id=task.creada_por_id,
                fecha_comun=assignment["fecha_comun"],
                task=task,
            )
            for task, assignment in zip(created, assignments)
        )


class MySQLAssignmentStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @staticmethod
    def _reserve_number(cursor, empresa_id):
        cursor.execute(
            "INSERT INTO tareas_correlativoempresa (empresa_id, siguiente_numero) "
            "VALUES (%s, %s) ON DUPLICATE KEY UPDATE empresa_id = empresa_id",
            (empresa_id, 1),
        )
        cursor.execute(
            "SELECT siguiente_numero FROM tareas_correlativoempresa "
            "WHERE empresa_id = %s FOR UPDATE",
            (empresa_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("No se pudo reservar el correlativo de Tareas.")
        cursor.execute(
            "UPDATE tareas_correlativoempresa SET siguiente_numero = %s "
            "WHERE empresa_id = %s",
            (int(row[0]) + 1, empresa_id),
        )
        return int(row[0])

    def create(self, *, empresa_id, creador_id, assignments):
        created = []
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                for assignment in assignments:
                    number = self._reserve_number(cursor, empresa_id)
                    now = timezone.now()
                    cursor.execute(
                        "INSERT INTO tareas_tarea ("
                        "titulo,descripcion,prioridad,correlativo,anulada,"
                        "fechas_pendientes_confirmacion,cierre_completado,"
                        "requiere_evidencia_cierre,estado,responsable_id,empresa_id,"
                        "tipo_ambito,local_id,departamento_id,creada_por_id,"
                        "fecha_creacion,fecha_publicacion,fecha_asignacion,"
                        "fecha_tope,fecha_cumplimiento,todo_origen_id,tarea_origen_id"
                        ") VALUES ("
                        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
                        ")",
                        (
                            assignment["titulo"], assignment["descripcion"],
                            assignment["prioridad"], f"B{number:07d}", False,
                            False, False, False, Tarea.Estado.BORRADOR,
                            assignment["responsable_id"], empresa_id, None, None, None,
                            creador_id, now, None, None, None, None, None, None,
                        ),
                    )
                    task_id = cursor.lastrowid
                    cursor.execute(
                        "INSERT INTO tareas_tareareasignacion ("
                        "tarea_id,responsable_anterior_id,responsable_nuevo_id,"
                        "usuario_id,fecha,motivo"
                        ") VALUES (%s,%s,%s,%s,%s,%s)",
                        (
                            task_id, None, assignment["responsable_id"], creador_id,
                            assignment["fecha_comun"], assignment["motivo"],
                        ),
                    )
                    created.append(AssignmentTask(
                        id=task_id,
                        empresa_id=empresa_id,
                        correlativo=f"B{number:07d}",
                        titulo=assignment["titulo"],
                        descripcion=assignment["descripcion"],
                        prioridad=assignment["prioridad"],
                        responsable_id=assignment["responsable_id"],
                        creada_por_id=creador_id,
                        fecha_comun=assignment["fecha_comun"],
                    ))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return tuple(created)


def resolve_assignment_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise RuntimeError("No se pudo resolver BASE_TAREAS para la asignación.") from exc
    if context.backend_type == "DJANGO":
        return DjangoAssignmentStorage(context.django_alias)
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLAssignmentStorage(context.mysql_connection, context.database_name)
    raise RuntimeError("El backend de BASE_TAREAS no es válido para la asignación.")
