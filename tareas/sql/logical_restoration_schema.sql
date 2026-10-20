-- L5: ampliación aditiva del ledger para operaciones de restauración.
-- Contrato de preflight únicamente; no ejecutar sin autorización específica.
-- No modifica datos ni el manifiesto histórico de eliminación.
ALTER TABLE `tareas_eliminacion_operacion` ADD COLUMN `reverses_operation_id` varchar(32) NULL;
CREATE UNIQUE INDEX `tareas_delop_reverses_uniq` ON `tareas_eliminacion_operacion` (`reverses_operation_id`);
ALTER TABLE `tareas_eliminacion_operacion` ADD CONSTRAINT `tareas_eliminacion_o_reverses_operation_i_1b35b931_fk_tareas_el` FOREIGN KEY (`reverses_operation_id`) REFERENCES `tareas_eliminacion_operacion` (`operation_id`);
ALTER TABLE `tareas_eliminacion_operacion` ADD CONSTRAINT `tareas_delop_restore_link` CHECK (((`reverses_operation_id` IS NULL AND NOT (`result_code` = 'LOGICALLY_RESTORED')) OR (`result_code` = '' AND `reverses_operation_id` IS NOT NULL AND `status` = 'PENDING') OR (`result_code` = 'LOGICALLY_RESTORED' AND `reverses_operation_id` IS NOT NULL AND `status` = 'COMMITTED')));
ALTER TABLE `tareas_eliminacion_operacion` ADD CONSTRAINT `tareas_delop_restore_motive` CHECK (((NOT (`reverses_operation_id` IS NOT NULL) AND NOT (`result_code` = 'LOGICALLY_RESTORED')) OR (`motivo` IS NOT NULL AND NOT (`motivo` = '' AND `motivo` IS NOT NULL))));
