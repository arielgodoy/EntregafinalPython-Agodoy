-- BASE_TAREAS MYSQL - REGISTRO TECNICO DE OPERACIONES V001
-- Preparado para revision; no ejecutar directamente en produccion.
-- Requiere preflight: SELECT DATABASE() coincide con el database_name
-- configurado para el rol BASE_TAREAS.
-- No contiene USE, credenciales, FK cross-database ni DDL destructivo.

CREATE TABLE IF NOT EXISTS `tareas_master_operation` (
    `operation_id` char(36) NOT NULL,
    `entity_type` varchar(20) NOT NULL,
    `action` varchar(20) NOT NULL,
    `empresa_id` bigint NOT NULL,
    `actor_id` bigint NOT NULL,
    `payload_hash` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `status` varchar(10) NOT NULL DEFAULT 'PENDING',
    `result_id` bigint NULL,
    `result_payload` json NULL,
    `audit_status` varchar(10) NOT NULL DEFAULT 'PENDING',
    `audit_event_id` bigint NULL,
    `audit_error_code` varchar(64) NOT NULL DEFAULT '',
    `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`operation_id`),
    KEY `tareas_master_operation_status_idx` (`status`, `updated_at`),
    KEY `tareas_master_operation_audit_idx` (`audit_status`, `updated_at`),
    KEY `tareas_master_operation_empresa_idx` (`empresa_id`, `created_at`),
    CONSTRAINT `tareas_master_operation_entity_ck`
        CHECK (`entity_type` IN ('PROVEEDOR', 'LOCAL', 'DEPARTAMENTO')),
    CONSTRAINT `tareas_master_operation_action_ck`
        CHECK (`action` IN ('CREATE', 'UPDATE', 'DELETE', 'RESTORE')),
    CONSTRAINT `tareas_master_operation_status_ck`
        CHECK (`status` IN ('PENDING', 'COMMITTED', 'FAILED', 'UNKNOWN')),
    CONSTRAINT `tareas_master_operation_audit_ck`
        CHECK (`audit_status` IN ('PENDING', 'CONFIRMED', 'ERROR')),
    CONSTRAINT `tareas_master_operation_error_ck`
        CHECK (
            (`audit_status` = 'ERROR' AND `audit_error_code` <> '')
            OR (`audit_status` <> 'ERROR' AND `audit_error_code` = '')
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
