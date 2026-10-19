-- Adición contractual para bases BASE_TAREAS MYSQL_CONFIG ya existentes.
-- Solo lectura desde el servicio de esquema; no ejecutar sin autorización específica.
-- Verificar columnas, índices y restricciones presentes antes de aplicar cada sentencia.
ALTER TABLE `tareas_tarea` ADD COLUMN `eliminada` bool NOT NULL DEFAULT 0;
ALTER TABLE `tareas_tarea` ADD COLUMN `eliminada_en` datetime(6) NULL;
ALTER TABLE `tareas_tarea` ADD COLUMN `eliminada_por_id` integer NULL;
ALTER TABLE `tareas_tarea` ADD COLUMN `eliminacion_operacion_id` char(32) NULL;
ALTER TABLE `tareas_tarea` ADD CONSTRAINT `tareas_elim_metadata_consistent` CHECK (((`eliminada` = 0 AND `eliminada_en` IS NULL AND `eliminada_por_id` IS NULL AND `eliminacion_operacion_id` IS NULL) OR (`eliminada` = 1 AND `eliminada_en` IS NOT NULL AND `eliminada_por_id` IS NOT NULL AND `eliminacion_operacion_id` IS NOT NULL)));
CREATE INDEX `tareas_emp_elim_idx` ON `tareas_tarea` (`empresa_id`, `eliminada`);
CREATE INDEX `tareas_delop_task_idx` ON `tareas_tarea` (`eliminacion_operacion_id`);
ALTER TABLE `tareas_eliminacion_operacion` ADD COLUMN `motivo` longtext NULL;
ALTER TABLE `tareas_eliminacion_operacion` ADD CONSTRAINT `tareas_delop_motivo_required` CHECK ((`result_code` <> 'LOGICALLY_DELETED' OR (`motivo` IS NOT NULL AND `motivo` <> '')));
