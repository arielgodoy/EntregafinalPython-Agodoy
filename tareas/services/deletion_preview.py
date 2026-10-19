"""Read-only inventory for the future permanent task deletion workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from django.db.models import Q

from .base_tareas_schema import get_operational_models
from .connection_roles import resolve_operational_backend
from .task_storage import TaskStorageError
from settings.services.mysql_connections import open_mysql_connection

from ..models import (
    Avance,
    Comentario,
    ComentarioAdjunto,
    ComentarioPausaLectura,
    ComentarioVersion,
    ComentarioVersionDocumento,
    Cotizacion,
    DocumentoCotizacion,
    DocumentoHistorial,
    DocumentoTarea,
    EnlaceTarea,
    EvaluacionSimilitud,
    EvidenciaCierre,
    EventoAccesoEnlace,
    Hito,
    HitoEvidencia,
    HitoHistorial,
    MiniTarea,
    MiniTareaEvento,
    ReunionRevision,
    ReunionParticipante,
    ReunionTarea,
    Reprogramacion,
    RondaCotizacion,
    Tarea,
    TareaAnulacionSnapshot,
    TareaCierre,
    TareaLectura,
    TareaParticipante,
    TareaReasignacion,
    TareaRelacion,
    TareaTransicion,
    TodoEvento,
)


class DeletionPreviewError(TaskStorageError):
    """A safe, user-facing preview could not be generated."""


class DeletionPreviewNotFound(DeletionPreviewError):
    """The root task is absent or outside the active company."""


class DeletionPreviewSchemaIncomplete(DeletionPreviewError):
    """The selected backend does not contain the expected Tareas schema."""

    def __init__(self, missing_tables):
        self.missing_tables = tuple(missing_tables)
        super().__init__("El esquema de tareas está incompleto.")


@dataclass
class _Inventory:
    task_ids: list[int]
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    shared_references: list[dict[str, object]] = field(default_factory=list)


class _DjangoReader:
    def __init__(self, alias):
        from django.db import connections

        self.alias = alias
        existing = set(connections[alias].introspection.table_names())
        self.missing_tables = tuple(
            model._meta.db_table
            for model in get_operational_models()
            if model._meta.db_table not in existing
        )

    def task(self, task_id, empresa_id):
        try:
            task = Tarea.objects.using(self.alias).get(
                pk=task_id,
                empresa_id=empresa_id,
            )
        except Tarea.DoesNotExist as exc:
            raise DeletionPreviewNotFound from exc
        return {
            "id": task.pk,
            "empresa_id": task.empresa_id,
            "correlativo": task.correlativo,
            "titulo": task.titulo,
            "estado": task.estado,
        }

    def tasks(self, task_ids, empresa_id):
        return list(
            Tarea.objects.using(self.alias)
            .filter(
                pk__in=task_ids,
                empresa_id=empresa_id,
                eliminada=False,
            )
            .order_by("pk")
            .values("id", "correlativo", "titulo", "estado")
        )

    def children(self, task_id, empresa_id):
        return list(
            TareaRelacion.objects.using(self.alias)
            .filter(
                padre_id=task_id,
                hija__empresa_id=empresa_id,
                hija__eliminada=False,
            )
            .order_by("hija_id")
            .values_list("hija_id", flat=True)
        )

    def companies(self, task_ids):
        return dict(
            Tarea.objects.using(self.alias)
            .filter(pk__in=task_ids)
            .values_list("pk", "empresa_id")
        )

    def related_ids(self, model, field_name, parent_ids):
        if not parent_ids:
            return []
        result = set()
        for batch in _batches(parent_ids):
            result.update(
                model.objects.using(self.alias)
                .filter(**{f"{field_name}__in": batch})
                .values_list("pk", flat=True)
            )
        return sorted(result)

    def related_count(self, model, field_name, parent_ids):
        return len(self.related_ids(model, field_name, parent_ids))

    def related_ids_any(self, model, fields, parent_ids=None):
        result = set()
        for field_name, field_ids in fields.items():
            result.update(self.related_ids(model, field_name, field_ids))
        return sorted(result)

    def task_references(self, affected_ids):
        outside = (
            Tarea.objects.using(self.alias)
            .filter(tarea_origen_id__in=affected_ids)
            .exclude(pk__in=affected_ids)
            .count()
        )
        return outside

    def todo_source_references(self, affected_ids):
        return Tarea.objects.using(self.alias).filter(
            pk__in=affected_ids,
            todo_origen_id__isnull=False,
        ).count()

    def external_hierarchy_references(self, affected_ids):
        rows = list(
            TareaRelacion.objects.using(self.alias)
            .filter(Q(padre_id__in=affected_ids) | Q(hija_id__in=affected_ids))
            .exclude(padre_id__in=affected_ids, hija_id__in=affected_ids)
            .values_list("padre_id", "hija_id")
        )
        return _classify_hierarchy_boundary(self, rows, affected_ids)

    def external_read_references(self, affected_ids, comment_ids):
        return TareaLectura.objects.using(self.alias).filter(
            comentario_leido_hasta_id__in=comment_ids
        ).exclude(tarea_id__in=affected_ids).count()

    def external_minitask_comment_events(self, affected_ids, comment_ids):
        return MiniTareaEvento.objects.using(self.alias).filter(
            comentario_feed_id__in=comment_ids
        ).exclude(mini_tarea__tarea_id__in=affected_ids).count()

    def related_meetings(self, affected_ids):
        planned_ids = list(
            ReunionRevision.objects.using(self.alias)
            .filter(tarea_planificada_id__in=affected_ids)
            .values_list("pk", flat=True)
        )
        agenda_ids = list(
            ReunionTarea.objects.using(self.alias)
            .filter(tarea_id__in=affected_ids)
            .values_list("reunion_id", flat=True)
        )
        return sorted(set(planned_ids + agenda_ids))

    def meeting_has_external_tasks(self, meeting_ids, affected_ids):
        return ReunionTarea.objects.using(self.alias).filter(
            reunion_id__in=meeting_ids
        ).exclude(tarea_id__in=affected_ids).exists()

    def shared_similarities(self, affected_ids):
        rows = EvaluacionSimilitud.objects.using(self.alias).filter(
            Q(tarea_id__in=affected_ids) | Q(tarea_candidata_id__in=affected_ids)
        ).values_list("tarea_id", "tarea_candidata_id")
        return sum(
            1
            for left_id, right_id in rows
            if left_id not in affected_ids or right_id not in affected_ids
        )

    def file_references(self, file_rows):
        model_rows = (
            (HitoEvidencia, file_rows["hito"]),
            (DocumentoTarea, file_rows["documento"]),
            (EvidenciaCierre, file_rows["evidencia_cierre"]),
            (DocumentoCotizacion, file_rows["documento_cotizacion"]),
        )
        paths = {
            name
            for _model, entries in model_rows
            for _pk, name in entries
            if name
        }
        if not paths:
            return 0
        target_ids = {
            model: {pk for pk, name in entries if name}
            for model, entries in model_rows
        }
        shared = 0
        for model, _entries in model_rows:
            for path_batch in _batches(sorted(paths)):
                queryset = model.objects.using(self.alias).filter(archivo__in=path_batch)
                if target_ids[model]:
                    queryset = queryset.exclude(pk__in=target_ids[model])
                shared += queryset.count()
        return shared

    def file_rows(self, model, field_name, parent_ids):
        if not parent_ids:
            return []
        return list(
            model.objects.using(self.alias)
            .filter(**{f"{field_name}__in": parent_ids})
            .exclude(archivo="")
            .values_list("pk", "archivo")
        )


class _MySQLReader:
    def __init__(self, connection, database_name):
        self.connection = connection
        self.database_name = database_name
        self.cursor = connection.cursor()
        models = get_operational_models()
        tables = [model._meta.db_table for model in models]
        placeholders = ", ".join(["%s"] * len(tables))
        self.cursor.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN (" + placeholders + ")",
            (database_name, *tables),
        )
        present = {row[0] for row in self.cursor.fetchall()}
        self.missing_tables = tuple(table for table in tables if table not in present)

    def close(self):
        self.cursor.close()

    @staticmethod
    def _quote(identifier):
        return "`" + identifier.replace("`", "``") + "`"

    def _select_ids(self, model, field_name, parent_ids):
        if not parent_ids:
            return []
        field = model._meta.get_field(field_name)
        table = self._quote(model._meta.db_table)
        pk_column = self._quote(model._meta.pk.column)
        column = self._quote(field.column)
        result = set()
        for batch in _batches(parent_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT DISTINCT {pk_column} FROM {table} "
                f"WHERE {column} IN ({placeholders})",
                tuple(batch),
            )
            result.update(row[0] for row in self.cursor.fetchall())
        return sorted(result)

    def _select_values(self, model, value_field, filter_field, parent_ids):
        if not parent_ids:
            return []
        table = self._quote(model._meta.db_table)
        value_column = self._quote(model._meta.get_field(value_field).column)
        filter_column = self._quote(model._meta.get_field(filter_field).column)
        result = set()
        for batch in _batches(parent_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT DISTINCT {value_column} FROM {table} "
                f"WHERE {filter_column} IN ({placeholders})",
                tuple(batch),
            )
            result.update(row[0] for row in self.cursor.fetchall())
        return sorted(result)

    def related_ids(self, model, field_name, parent_ids):
        return self._select_ids(model, field_name, parent_ids)

    def related_ids_any(self, model, fields, parent_ids=None):
        result = set()
        for field_name, field_ids in fields.items():
            result.update(self.related_ids(model, field_name, field_ids))
        return sorted(result)

    def related_count(self, model, field_name, parent_ids):
        return len(self.related_ids(model, field_name, parent_ids))

    def task(self, task_id, empresa_id):
        table = self._quote(Tarea._meta.db_table)
        self.cursor.execute(
            f"SELECT id, empresa_id, correlativo, titulo, estado FROM {table} "
            "WHERE id = %s AND empresa_id = %s AND eliminada = %s",
            (task_id, empresa_id, False),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise DeletionPreviewNotFound
        return dict(
            id=row[0],
            empresa_id=row[1],
            correlativo=row[2],
            titulo=row[3],
            estado=row[4],
        )

    def tasks(self, task_ids, empresa_id):
        if not task_ids:
            return []
        table = self._quote(Tarea._meta.db_table)
        id_column = self._quote(Tarea._meta.pk.column)
        company_column = self._quote(Tarea._meta.get_field("empresa").column)
        deleted_column = self._quote(Tarea._meta.get_field("eliminada").column)
        correlativo_column = self._quote(Tarea._meta.get_field("correlativo").column)
        title_column = self._quote(Tarea._meta.get_field("titulo").column)
        state_column = self._quote(Tarea._meta.get_field("estado").column)
        records = []
        for batch in _batches(task_ids):
            placeholders = ", ".join("%s" for _ in batch)
            self.cursor.execute(
                f"SELECT {id_column}, {correlativo_column}, {title_column}, "
                f"{state_column} FROM {table} WHERE {company_column} = %s "
                f"AND {deleted_column} = %s AND {id_column} IN ({placeholders}) "
                f"ORDER BY {id_column}",
                (empresa_id, False, *batch),
            )
            records.extend(
                dict(
                    id=row[0],
                    correlativo=row[1],
                    titulo=row[2],
                    estado=row[3],
                )
                for row in self.cursor.fetchall()
            )
        return records

    def children(self, task_id, empresa_id):
        relation = self._quote(TareaRelacion._meta.db_table)
        task_table = self._quote(Tarea._meta.db_table)
        parent_column = self._quote(TareaRelacion._meta.get_field("padre").column)
        child_column = self._quote(TareaRelacion._meta.get_field("hija").column)
        task_id_column = self._quote(Tarea._meta.pk.column)
        company_column = self._quote(Tarea._meta.get_field("empresa").column)
        deleted_column = self._quote(Tarea._meta.get_field("eliminada").column)
        self.cursor.execute(
            f"SELECT rel.{child_column} FROM {relation} AS rel "
            f"INNER JOIN {task_table} AS child_task "
            f"ON child_task.{task_id_column} = rel.{child_column} "
            f"WHERE rel.{parent_column} = %s "
            f"AND child_task.{company_column} = %s "
            f"AND child_task.{deleted_column} = %s "
            f"ORDER BY rel.{child_column}",
            (task_id, empresa_id, False),
        )
        return [row[0] for row in self.cursor.fetchall()]

    def companies(self, task_ids):
        if not task_ids:
            return {}
        result = {}
        table = self._quote(Tarea._meta.db_table)
        for batch in _batches(task_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT id, empresa_id FROM {table} WHERE id IN ({placeholders})",
                tuple(batch),
            )
            result.update(self.cursor.fetchall())
        return result

    def task_references(self, affected_ids):
        model = Tarea
        field = model._meta.get_field("tarea_origen")
        table = self._quote(model._meta.db_table)
        column = self._quote(field.column)
        pk_column = self._quote(model._meta.pk.column)
        referenced_ids = set()
        for batch in _batches(affected_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT {pk_column} FROM {table} WHERE {column} IN ({placeholders})",
                tuple(batch),
            )
            referenced_ids.update(row[0] for row in self.cursor.fetchall())
        return len(referenced_ids - set(affected_ids))

    def todo_source_references(self, affected_ids):
        model = Tarea
        table = self._quote(model._meta.db_table)
        pk_column = self._quote(model._meta.pk.column)
        todo_column = self._quote(model._meta.get_field("todo_origen").column)
        count = 0
        for batch in _batches(affected_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {pk_column} IN "
                f"({placeholders}) AND {todo_column} IS NOT NULL",
                tuple(batch),
            )
            count += int(self.cursor.fetchone()[0])
        return count

    def _count_external_reference(self, model, left_field, right_field, ids):
        if not ids:
            return 0
        table = self._quote(model._meta.db_table)
        left_column = self._quote(model._meta.get_field(left_field).column)
        right_column = self._quote(model._meta.get_field(right_field).column)
        count = 0
        for batch in _batches(ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {left_column} IN ({placeholders}) "
                f"AND {right_column} NOT IN ({placeholders})",
                (*batch, *batch),
            )
            count += int(self.cursor.fetchone()[0])
        return count

    def external_hierarchy_references(self, affected_ids):
        table = self._quote(TareaRelacion._meta.db_table)
        parent_column = self._quote(TareaRelacion._meta.get_field("padre").column)
        child_column = self._quote(TareaRelacion._meta.get_field("hija").column)
        references = set()
        for batch in _batches(affected_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT {parent_column}, {child_column} FROM {table} WHERE "
                f"{parent_column} IN ({placeholders}) OR {child_column} IN ({placeholders})",
                (*batch, *batch),
            )
            references.update(self.cursor.fetchall())
        return _classify_hierarchy_boundary(
            self,
            sorted(references),
            affected_ids,
        )

    def external_read_references(self, affected_ids, comment_ids):
        if not comment_ids:
            return 0
        model = TareaLectura
        table = self._quote(model._meta.db_table)
        comment_col = self._quote(model._meta.get_field("comentario_leido_hasta").column)
        task_col = self._quote(model._meta.get_field("tarea").column)
        reading_task_ids = set()
        for comment_batch in _batches(comment_ids):
            placeholders_comments = ", ".join(["%s"] * len(comment_batch))
            self.cursor.execute(
                f"SELECT {task_col} FROM {table} WHERE {comment_col} IN "
                f"({placeholders_comments})",
                tuple(comment_batch),
            )
            reading_task_ids.update(row[0] for row in self.cursor.fetchall())
        return len(reading_task_ids - set(affected_ids))

    def external_minitask_comment_events(self, affected_ids, comment_ids):
        if not comment_ids:
            return 0
        event_table = self._quote(MiniTareaEvento._meta.db_table)
        mini_table = self._quote(MiniTarea._meta.db_table)
        comment_col = self._quote(MiniTareaEvento._meta.get_field("comentario_feed").column)
        mini_col = self._quote(MiniTareaEvento._meta.get_field("mini_tarea").column)
        event_pk = self._quote(MiniTareaEvento._meta.pk.column)
        mini_pk = self._quote(MiniTarea._meta.pk.column)
        mini_task_col = self._quote(MiniTarea._meta.get_field("tarea").column)
        external_mini_ids = set()
        for comment_batch in _batches(comment_ids):
            placeholders_comments = ", ".join(["%s"] * len(comment_batch))
            self.cursor.execute(
                f"SELECT event.{event_pk}, mini.{mini_task_col} FROM {event_table} event "
                f"JOIN {mini_table} mini ON mini.{mini_pk} = event.{mini_col} "
                f"WHERE event.{comment_col} IN ({placeholders_comments})",
                tuple(comment_batch),
            )
            external_mini_ids.update(
                event_id
                for event_id, task_id in self.cursor.fetchall()
                if task_id not in affected_ids
            )
        return len(external_mini_ids)

    def related_meetings(self, affected_ids):
        result = set(self.related_ids(ReunionRevision, "tarea_planificada", affected_ids))
        result.update(
            self._select_values(ReunionTarea, "reunion", "tarea", affected_ids)
        )
        return sorted(result)

    def meeting_has_external_tasks(self, meeting_ids, affected_ids):
        if not meeting_ids:
            return False
        model = ReunionTarea
        table = self._quote(model._meta.db_table)
        meeting_col = self._quote(model._meta.get_field("reunion").column)
        task_col = self._quote(model._meta.get_field("tarea").column)
        for batch in _batches(meeting_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            task_placeholders = ", ".join(["%s"] * len(affected_ids))
            self.cursor.execute(
                f"SELECT 1 FROM {table} WHERE {meeting_col} IN ({placeholders}) "
                f"AND {task_col} NOT IN ({task_placeholders}) LIMIT 1",
                (*batch, *affected_ids),
            )
            if self.cursor.fetchone():
                return True
        return False

    def shared_similarities(self, affected_ids):
        if not affected_ids:
            return 0
        table = self._quote(EvaluacionSimilitud._meta.db_table)
        left = self._quote(EvaluacionSimilitud._meta.get_field("tarea").column)
        right = self._quote(EvaluacionSimilitud._meta.get_field("tarea_candidata").column)
        count = 0
        for batch in _batches(affected_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT {left}, {right} FROM {table} WHERE {left} IN ({placeholders}) "
                f"OR {right} IN ({placeholders})",
                (*batch, *batch),
            )
            count += sum(
                1
                for left_id, right_id in self.cursor.fetchall()
                if left_id not in affected_ids or right_id not in affected_ids
            )
        return count

    def file_rows(self, model, field_name, parent_ids):
        if not parent_ids:
            return []
        table = self._quote(model._meta.db_table)
        pk_column = self._quote(model._meta.pk.column)
        file_column = self._quote(model._meta.get_field("archivo").column)
        parent_column = self._quote(model._meta.get_field(field_name).column)
        rows = []
        for batch in _batches(parent_ids):
            placeholders = ", ".join(["%s"] * len(batch))
            self.cursor.execute(
                f"SELECT {pk_column}, {file_column} FROM {table} "
                f"WHERE {parent_column} IN ({placeholders}) AND {file_column} <> ''",
                tuple(batch),
            )
            rows.extend(self.cursor.fetchall())
        return rows

    def file_references(self, file_rows):
        models_fields = (
            (HitoEvidencia, "archivo"),
            (DocumentoTarea, "archivo"),
            (EvidenciaCierre, "archivo"),
            (DocumentoCotizacion, "archivo"),
        )
        paths = sorted(
            {
                name
                for entries in file_rows.values()
                for _pk, name in entries
                if name
            }
        )
        shared = 0
        for model, _field_name in models_fields:
            table = self._quote(model._meta.db_table)
            file_column = self._quote(model._meta.get_field("archivo").column)
            for batch in _batches(paths):
                placeholders = ", ".join(["%s"] * len(batch))
                self.cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {file_column} IN ({placeholders})",
                    tuple(batch),
                )
                shared += int(self.cursor.fetchone()[0])
        return max(0, shared - sum(len(entries) for entries in file_rows.values()))


def _batches(values, size=400):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _classify_hierarchy_boundary(reader, rows, affected_ids):
    affected = set(affected_ids)
    reference_ids = {
        node_id
        for parent_id, child_id in rows
        for node_id in (parent_id, child_id)
    }
    companies = reader.companies(sorted(reference_ids))
    same_company_parent_links = 0
    blocking_links = 0
    for parent_id, child_id in rows:
        if parent_id in affected and child_id in affected:
            continue
        parent_company = companies.get(parent_id)
        child_company = companies.get(child_id)
        if parent_id not in affected and child_id in affected:
            if parent_company is not None and parent_company == child_company:
                same_company_parent_links += 1
            else:
                blocking_links += 1
        else:
            blocking_links += 1
    return {
        "incoming_parent_links": same_company_parent_links,
        "blocking_links": blocking_links,
    }


def _collect_hierarchy(reader, root_id, empresa_id):
    adjacency = {}
    discovered = {root_id}
    queue = [root_id]
    blockers = []
    duplicate_edges = set()
    parent_by_child = {}
    while queue:
        parent_id = queue.pop(0)
        children = reader.children(parent_id, empresa_id)
        if len(children) != len(set(children)):
            duplicate_edges.add(parent_id)
        adjacency[parent_id] = sorted(set(children))
        unknown = set(children) - discovered
        for child_id in set(children):
            previous_parent = parent_by_child.setdefault(child_id, parent_id)
            if previous_parent != parent_id:
                blockers.append(
                    "La jerarquía contiene una tarea relacionada con más de un padre."
                )
        companies = reader.companies(sorted(unknown))
        for child_id in sorted(unknown):
            child_company = companies.get(child_id)
            if child_company is None or child_company != empresa_id:
                blockers.append(
                    "La jerarquía contiene una tarea hija no disponible "
                    "en el ámbito activo."
                )
            else:
                discovered.add(child_id)
                queue.append(child_id)
    if duplicate_edges:
        blockers.append("La jerarquía contiene relaciones duplicadas.")

    colors = {}
    for start_id in sorted(discovered):
        if colors.get(start_id, 0):
            continue
        stack = [(start_id, False)]
        while stack:
            task_id, exiting = stack.pop()
            if exiting:
                colors[task_id] = 2
                continue
            color = colors.get(task_id, 0)
            if color == 1:
                blockers.append("La jerarquía contiene un ciclo.")
                continue
            if color == 2:
                continue
            colors[task_id] = 1
            stack.append((task_id, True))
            for child_id in reversed(adjacency.get(task_id, ())):
                if child_id not in discovered:
                    continue
                if colors.get(child_id, 0) == 1:
                    blockers.append("La jerarquía contiene un ciclo.")
                elif colors.get(child_id, 0) == 0:
                    stack.append((child_id, False))
    ordered = []
    seen = set()
    stack = [root_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        stack.extend(
            child_id
            for child_id in reversed(adjacency.get(current, ()))
            if child_id in discovered
        )
    return ordered, blockers


def _inventory_dependencies(
    reader,
    inventory,
    *,
    purpose: Literal["physical", "logical"],
):
    task_ids = inventory.task_ids
    counts = inventory.counts

    hito_ids = reader.related_ids(Hito, "tarea", task_ids)
    mini_ids = reader.related_ids(MiniTarea, "tarea", task_ids)
    document_ids = reader.related_ids(DocumentoTarea, "tarea", task_ids)
    comment_ids = reader.related_ids(Comentario, "tarea", task_ids)
    reading_ids = reader.related_ids(TareaLectura, "tarea", task_ids)
    link_ids = reader.related_ids(EnlaceTarea, "tarea", task_ids)
    reprogramming_ids = reader.related_ids(Reprogramacion, "tarea", task_ids)
    round_ids = reader.related_ids(RondaCotizacion, "tarea", task_ids)
    quote_ids = reader.related_ids(Cotizacion, "ronda", round_ids)
    version_ids = reader.related_ids(ComentarioVersion, "comentario", comment_ids)
    meetings = reader.related_meetings(task_ids)

    related = (
        ("Avances", Avance, "tarea", task_ids),
        ("Hitos", Hito, "tarea", task_ids),
        ("Historiales de hitos", HitoHistorial, "hito", hito_ids),
        ("Evidencias de hitos", HitoEvidencia, "hito", hito_ids),
        ("Minitareas", MiniTarea, "tarea", task_ids),
        ("Documentos", DocumentoTarea, "tarea", task_ids),
        ("Historiales documentales", DocumentoHistorial, "documento", document_ids),
        ("Evidencias de cierre", EvidenciaCierre, "tarea", task_ids),
        ("Comentarios", Comentario, "tarea", task_ids),
        ("Versiones de comentarios", ComentarioVersion, "comentario", comment_ids),
        ("Lecturas", TareaLectura, "tarea", task_ids),
        ("Pausas de lectura", ComentarioPausaLectura, "lectura", reading_ids),
        ("Participantes", TareaParticipante, "tarea", task_ids),
        ("Asignaciones", TareaReasignacion, "tarea", task_ids),
        ("Reprogramaciones", Reprogramacion, "tarea", task_ids),
        ("Transiciones", TareaTransicion, "tarea", task_ids),
        ("Cierres", TareaCierre, "tarea", task_ids),
        ("Snapshots de anulación", TareaAnulacionSnapshot, "tarea", task_ids),
        ("Enlaces compartidos", EnlaceTarea, "tarea", task_ids),
        ("Eventos de acceso a enlaces", EventoAccesoEnlace, "enlace", link_ids),
        ("Eventos relacionados con Todo", TodoEvento, "tarea", task_ids),
        ("Rondas de cotización", RondaCotizacion, "tarea", task_ids),
        ("Cotizaciones", Cotizacion, "ronda", round_ids),
        ("Documentos de cotización", DocumentoCotizacion, "cotizacion", quote_ids),
    )
    for label, model, field_name, parent_ids in related:
        counts[label] = reader.related_count(model, field_name, parent_ids)

    attachment_ids = reader.related_ids_any(
        ComentarioAdjunto,
        {"comentario": comment_ids, "documento": document_ids},
    )
    version_document_ids = reader.related_ids_any(
        ComentarioVersionDocumento,
        {"version": version_ids, "documento": document_ids},
    )
    mini_event_ids = reader.related_ids_any(
        MiniTareaEvento,
        {"mini_tarea": mini_ids, "comentario_feed": comment_ids},
    )
    counts["Eventos de minitareas"] = len(mini_event_ids)
    counts["Adjuntos de comentarios"] = len(attachment_ids)
    counts["Documentos de versiones de comentarios"] = len(version_document_ids)
    counts["Eventos de minitareas"] = len(mini_event_ids)

    relation_parent_ids = reader.related_ids(TareaRelacion, "padre", task_ids)
    relation_child_ids = reader.related_ids(TareaRelacion, "hija", task_ids)
    counts["Relaciones jerárquicas"] = len(
        set(relation_parent_ids) | set(relation_child_ids)
    )
    hierarchy_boundary = reader.external_hierarchy_references(task_ids)
    if hierarchy_boundary["incoming_parent_links"]:
        incoming_links = hierarchy_boundary["incoming_parent_links"]
        inventory.shared_references.append(
            {
                "type": "hierarchy_parent",
                "count": incoming_links,
                "classification": "ELIMINABLE",
                "message": "La tarea seleccionada tiene relación con una tarea superior que queda fuera del alcance.",
            }
        )
        inventory.warnings.append(
            "La relación con la tarea superior no amplía el alcance de descendientes."
        )
    if hierarchy_boundary["blocking_links"]:
        blocking_links = hierarchy_boundary["blocking_links"]
        inventory.shared_references.append(
            {
                "type": "hierarchy",
                "count": blocking_links,
                "classification": "BLOQUEANTE",
                "message": "Hay relaciones jerárquicas con tareas fuera del alcance.",
            }
        )
        inventory.blockers.append(
            "Hay relaciones jerárquicas que conectan el alcance con tareas externas."
        )
    counts["Reuniones relacionadas"] = len(meetings)
    counts["Agendas de reuniones"] = reader.related_count(
        ReunionTarea, "reunion", meetings
    )
    counts["Participantes de reuniones relacionadas"] = reader.related_count(
        ReunionParticipante, "reunion", meetings
    )
    counts["Asociaciones de causas de reprogramación"] = reader.related_count(
        Reprogramacion.causas.through, "reprogramacion", reprogramming_ids
    )

    shared_similarities = reader.shared_similarities(task_ids)
    if shared_similarities:
        inventory.shared_references.append(
            {
                "type": "similarity",
                "count": shared_similarities,
                "classification": "BLOQUEANTE",
                "message": "Hay evaluaciones de similitud con tareas externas al alcance.",
            }
        )
        inventory.blockers.append(
            "Hay evaluaciones de similitud que también referencian tareas externas."
        )

    if meetings and reader.meeting_has_external_tasks(meetings, task_ids):
        inventory.shared_references.append(
            {
                "type": "meetings",
                "count": len(meetings),
                "classification": "BLOQUEANTE",
                "message": "Al menos una reunión contiene tareas fuera del alcance.",
            }
        )
        inventory.blockers.append(
            "Hay reuniones compartidas con tareas fuera del alcance."
        )

    outside_origins = reader.task_references(task_ids)
    if outside_origins:
        inventory.shared_references.append(
            {
                "type": "task_origin",
                "count": outside_origins,
                "classification": "BLOQUEANTE",
                "message": "Tareas externas declaran como origen una tarea afectada.",
            }
        )
        inventory.blockers.append(
            "Hay tareas externas que referencian una tarea del alcance como origen."
        )

    todo_refs = reader.todo_source_references(task_ids)
    counts["Tareas con Todo de origen"] = todo_refs
    if todo_refs:
        inventory.shared_references.append(
            {
                "type": "todo_origin",
                "count": todo_refs,
                "classification": "PRESERVAR",
                "message": "Las tareas afectadas tienen objetos Todo de origen fuera del alcance de tareas.",
            }
        )

    inventory.shared_references.append(
        {
            "type": "external_references",
            "classification": "NO_VERIFICADA",
            "message": (
                "No se inventariaron notificaciones externas ni referencias lógicas "
                "desde otros módulos."
            ),
        }
    )

    external_readers = reader.external_read_references(task_ids, comment_ids)
    external_comment_events = reader.external_minitask_comment_events(
        task_ids,
        comment_ids,
    )
    if external_readers or external_comment_events:
        external_count = external_readers + external_comment_events
        inventory.shared_references.append(
            {
                "type": "comment_references",
                "count": external_count,
                "classification": "BLOQUEANTE",
                "message": "Otros registros operacionales hacen referencia a comentarios afectados.",
            }
        )
        inventory.blockers.append(
            "Hay lecturas o eventos de minitareas externos que referencian comentarios afectados."
        )

    hito_files = reader.file_rows(HitoEvidencia, "hito", hito_ids)
    document_files = reader.file_rows(DocumentoTarea, "tarea", task_ids)
    closure_files = reader.file_rows(EvidenciaCierre, "tarea", task_ids)
    quote_files = reader.file_rows(DocumentoCotizacion, "cotizacion", quote_ids)
    shared_file_refs = reader.file_references(
        {
            "hito": hito_files,
            "documento": document_files,
            "evidencia_cierre": closure_files,
            "documento_cotizacion": quote_files,
        }
    )
    counts["Referencias de archivos compartidas en Tareas"] = shared_file_refs
    if shared_file_refs:
        inventory.shared_references.append(
            {
                "type": "files",
                "count": shared_file_refs,
                "classification": (
                    "BLOQUEANTE" if purpose == "physical" else "PRESERVAR"
                ),
                "message": (
                    "Hay archivos con referencias adicionales en tablas de Tareas."
                    if purpose == "physical"
                    else "La operación lógica conservará las referencias de archivos compartidas."
                ),
            }
        )
        if purpose == "physical":
            inventory.blockers.append(
                "Hay archivos referenciados por otros registros de Tareas."
            )
    if any((hito_files, document_files, closure_files, quote_files)):
        if purpose == "physical":
            inventory.warnings.append(
                "No se verificaron referencias de archivos fuera de las tablas de Tareas."
            )
            inventory.blockers.append(
                "La exclusividad de archivos físicos frente a otros módulos no está verificada."
            )
        else:
            inventory.warnings.append(
                "La eliminación lógica conservará los documentos y archivos; no se ejecutará limpieza física."
            )


def build_deletion_preview(
    *,
    task_id,
    empresa_id,
    purpose: Literal["physical", "logical"] = "physical",
):
    """Build a read-only inventory; file-exclusivity blockers depend on purpose."""
    if purpose not in {"physical", "logical"}:
        raise DeletionPreviewError("El propósito de previsualización no es válido.")
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            reader = _DjangoReader(context.django_alias)
            backend = "DJANGO"
        elif context.backend_type == "MYSQL_CONFIG":
            with open_mysql_connection(
                context.mysql_connection,
                database_name=context.database_name,
            ) as connection:
                reader = _MySQLReader(connection, context.database_name)
                backend = "MYSQL"
                try:
                    if reader.missing_tables:
                        raise DeletionPreviewSchemaIncomplete(reader.missing_tables)
                    task = reader.task(task_id, empresa_id)
                    task_ids, hierarchy_blockers = _collect_hierarchy(
                        reader, task_id, empresa_id
                    )
                    inventory = _Inventory(task_ids)
                    inventory.blockers.extend(hierarchy_blockers)
                    inventory.counts["Tareas descendientes"] = max(0, len(task_ids) - 1)
                    _inventory_dependencies(
                        reader,
                        inventory,
                        purpose=purpose,
                    )
                    tasks = reader.tasks(task_ids, empresa_id)
                    if {task["id"] for task in tasks} != set(task_ids):
                        inventory.blockers.append(
                            "El árbol cambió durante la generación de la previsualización."
                        )
                    return _serialize_preview(
                        task,
                        inventory,
                        backend,
                        tasks,
                    )
                finally:
                    reader.close()
        else:
            raise DeletionPreviewError("Backend de Tareas no válido.")
    except DeletionPreviewError:
        raise
    except Exception as exc:
        raise DeletionPreviewError(
            "No se pudo generar la previsualización del inventario."
        ) from exc

    if reader.missing_tables:
        raise DeletionPreviewSchemaIncomplete(reader.missing_tables)
    task = reader.task(task_id, empresa_id)
    task_ids, hierarchy_blockers = _collect_hierarchy(reader, task_id, empresa_id)
    inventory = _Inventory(task_ids)
    inventory.blockers.extend(hierarchy_blockers)
    inventory.counts["Tareas descendientes"] = max(0, len(task_ids) - 1)
    _inventory_dependencies(
        reader,
        inventory,
        purpose=purpose,
    )
    tasks = reader.tasks(task_ids, empresa_id)
    if {task["id"] for task in tasks} != set(task_ids):
        inventory.blockers.append(
            "El árbol cambió durante la generación de la previsualización."
        )
    return _serialize_preview(
        task,
        inventory,
        backend,
        tasks,
    )


def _serialize_preview(task, inventory, backend, tasks):
    tasks_by_id = {item["id"]: item for item in tasks}
    return {
        "task": task,
        "task_count": len(inventory.task_ids),
        "descendant_count": max(0, len(inventory.task_ids) - 1),
        "task_ids": inventory.task_ids,
        "tasks": [
            tasks_by_id[task_id]
            for task_id in inventory.task_ids
            if task_id in tasks_by_id
        ],
        "counts": inventory.counts,
        "shared_references": inventory.shared_references,
        "warnings": sorted(set(inventory.warnings)),
        "blockers": sorted(set(inventory.blockers)),
        "integrity_status": "BLOCKED" if inventory.blockers else "CLEAR",
        "backend": backend,
    }
