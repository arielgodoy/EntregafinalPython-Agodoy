-- BASE_TAREAS MYSQL - MAESTROS V001
-- DDL versionado para Proveedores, Locales y Departamentos.
-- Preparado para revisión; no ejecutar directamente en producción.
-- La base física la selecciona el rol configurable BASE_TAREAS.
-- No contiene USE, credenciales, FK cross-database ni DDL destructivo.

CREATE TABLE IF NOT EXISTS `proveedores_proveedor` (
    `id` bigint NOT NULL AUTO_INCREMENT,
    `rut` varchar(12) NULL,
    `nombre` varchar(255) NOT NULL,
    `direccion` varchar(255) NOT NULL DEFAULT '',
    `comuna` varchar(100) NOT NULL DEFAULT '',
    `ciudad` varchar(100) NOT NULL DEFAULT '',
    `fono1` varchar(30) NOT NULL DEFAULT '',
    `fono2` varchar(30) NOT NULL DEFAULT '',
    `fax` varchar(30) NOT NULL DEFAULT '',
    `contacto` varchar(150) NOT NULL DEFAULT '',
    `email1` varchar(254) NOT NULL DEFAULT '',
    `email2` varchar(254) NOT NULL DEFAULT '',
    `activo` tinyint(1) NOT NULL DEFAULT 1,
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `proveedores_proveedor_rut_uniq` (`rut`),
    KEY `proveedores_proveedor_nombre_idx` (`nombre`(191)),
    KEY `proveedores_proveedor_activo_nombre_idx` (`activo`, `nombre`(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `organizacion_local` (
    `id` bigint NOT NULL AUTO_INCREMENT,
    `empresa_id` bigint NOT NULL,
    `codigo` varchar(100) NOT NULL,
    `nombre` varchar(255) NOT NULL,
    `legacy_code` varchar(100) NULL,
    `activo` tinyint(1) NOT NULL DEFAULT 1,
    `source` varchar(5) NOT NULL,
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `organizacion_local_empresa_codigo_uniq` (`empresa_id`, `codigo`),
    KEY `organizacion_local_empresa_activo_idx` (`empresa_id`, `activo`),
    KEY `organizacion_local_empresa_source_idx` (`empresa_id`, `source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `organizacion_departamento` (
    `id` bigint NOT NULL AUTO_INCREMENT,
    `empresa_id` bigint NOT NULL,
    `codigo` varchar(100) NOT NULL,
    `nombre` varchar(255) NOT NULL,
    `activo` tinyint(1) NOT NULL DEFAULT 1,
    `source` varchar(5) NOT NULL,
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `organizacion_departamento_empresa_codigo_uniq` (
        `empresa_id`,
        `codigo`
    ),
    KEY `organizacion_departamento_empresa_activo_idx` (`empresa_id`, `activo`),
    KEY `organizacion_departamento_empresa_source_idx` (`empresa_id`, `source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
