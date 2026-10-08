CREATE TABLE `gestiondte_certificadosii` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `empresa_codigo` VARCHAR(10) NOT NULL,
    `archivo` VARCHAR(100) NOT NULL,
    `password_encrypted` LONGBLOB NULL,
    `activo` TINYINT(1) NOT NULL DEFAULT 0,
    `titular` VARCHAR(255) NULL,
    `emisor_certificado` VARCHAR(255) NULL,
    `numero_serie` VARCHAR(255) NULL,
    `rut_titular` VARCHAR(64) NULL,
    `valido_desde` DATETIME(6) NULL,
    `valido_hasta` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `created_by_id` INT NULL,
    `created_by_username` VARCHAR(150) NULL,
    `updated_by_id` INT NULL,
    `updated_by_username` VARCHAR(150) NULL,
    PRIMARY KEY (`id`),
    KEY `gestiondte_cert_empresa_idx` (`empresa_codigo`),
    KEY `gestiondte_cert_created_by_idx` (`created_by_id`),
    KEY `gestiondte_cert_updated_by_idx` (`updated_by_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_tarearpetc` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `empresa_codigo` VARCHAR(2) NOT NULL,
    `id_tarea` VARCHAR(64) NOT NULL,
    `tipo_consulta` VARCHAR(20) NOT NULL,
    `rut_consultado` VARCHAR(12) NOT NULL,
    `dv_consultado` VARCHAR(2) NOT NULL,
    `fecha_desde` DATE NOT NULL,
    `fecha_hasta` DATE NOT NULL,
    `formato` VARCHAR(4) NOT NULL,
    `rut_autenticado` VARCHAR(12) NULL,
    `dv_autenticado` VARCHAR(2) NULL,
    `nombre_tarea` VARCHAR(100) NULL,
    `estado` VARCHAR(30) NOT NULL,
    `resultado` VARCHAR(100) NULL,
    `hora_creado_sii` DATETIME(6) NULL,
    `hora_en_proceso_sii` DATETIME(6) NULL,
    `hora_terminado_sii` DATETIME(6) NULL,
    `file_size` BIGINT UNSIGNED NULL,
    `cantidad_lineas` INT UNSIGNED NULL,
    `comprimido` TINYINT(1) NULL,
    `codigo_error` VARCHAR(50) NULL,
    `descripcion_error` LONGTEXT NULL,
    `parametros` JSON NULL,
    `parametros_raw` LONGTEXT NULL,
    `consultada_en` DATETIME(6) NOT NULL,
    `actualizada_en` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `rpetc_tarea_id_tarea_uq` (`id_tarea`),
    KEY `rpetc_tarea_empresa_idx` (`empresa_codigo`),
    KEY `rpetc_tarea_emp_tipo_idx` (`empresa_codigo`, `tipo_consulta`),
    KEY `rpetc_tarea_estado_idx` (`estado`),
    KEY `rpetc_tarea_periodo_idx` (`fecha_desde`, `fecha_hasta`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_cesionrpetc` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `id_cesion` VARCHAR(64) NOT NULL,
    `estado_cesion` VARCHAR(80) NOT NULL,
    `vendedor_rut` VARCHAR(12) NULL,
    `vendedor_dv` VARCHAR(2) NULL,
    `deudor_rut` VARCHAR(12) NOT NULL,
    `deudor_dv` VARCHAR(2) NOT NULL,
    `deudor_email` VARCHAR(254) NULL,
    `tipo_doc` VARCHAR(10) NOT NULL,
    `nombre_doc` VARCHAR(100) NULL,
    `folio_doc` VARCHAR(40) NOT NULL,
    `fecha_emision` DATE NULL,
    `monto_total` DECIMAL(20, 0) NULL,
    `cedente_rut` VARCHAR(12) NULL,
    `cedente_dv` VARCHAR(2) NULL,
    `cedente_razon_social` VARCHAR(255) NULL,
    `cedente_email` VARCHAR(254) NULL,
    `cesionario_rut` VARCHAR(12) NULL,
    `cesionario_dv` VARCHAR(2) NULL,
    `cesionario_razon_social` VARCHAR(255) NULL,
    `cesionario_email` VARCHAR(254) NULL,
    `fecha_cesion` DATETIME(6) NULL,
    `monto_cesion` DECIMAL(20, 0) NULL,
    `fecha_vencimiento` DATE NULL,
    `detectada_en` DATETIME(6) NOT NULL,
    `actualizada_en` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `rpetc_cesion_identidad_unica` (`id_cesion`, `deudor_rut`, `deudor_dv`, `tipo_doc`, `folio_doc`),
    KEY `rpetc_cesion_id_idx` (`id_cesion`),
    KEY `rpetc_cesion_estado_idx` (`estado_cesion`),
    KEY `rpetc_cesion_vendedor_idx` (`vendedor_rut`),
    KEY `rpetc_cesion_deudor_idx` (`deudor_rut`),
    KEY `rpetc_cesion_emision_idx` (`fecha_emision`),
    KEY `rpetc_cesion_cedente_idx` (`cedente_rut`),
    KEY `rpetc_cesion_cesionario_idx` (`cesionario_rut`),
    KEY `rpetc_cesion_fecha_idx` (`fecha_cesion`),
    KEY `rpetc_cesion_doc_idx` (`tipo_doc`, `folio_doc`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_cesionrpetchistorial` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `cesion_id` BIGINT NOT NULL,
    `estado` VARCHAR(80) NOT NULL,
    `estado_anterior` VARCHAR(80) NULL,
    `fecha_detectado` DATETIME(6) NOT NULL,
    `tarea_origen_id` BIGINT NULL,
    `observacion` LONGTEXT NULL,
    PRIMARY KEY (`id`),
    KEY `rpetc_hist_cesion_fecha_idx` (`cesion_id`, `fecha_detectado`),
    KEY `rpetc_hist_tarea_idx` (`tarea_origen_id`),
    CONSTRAINT `rpetc_hist_cesion_fk` FOREIGN KEY (`cesion_id`)
        REFERENCES `gestiondte_cesionrpetc` (`id`),
    CONSTRAINT `rpetc_hist_tarea_fk` FOREIGN KEY (`tarea_origen_id`)
        REFERENCES `gestiondte_tarearpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_tareacesionrpetc` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `tarea_id` BIGINT NOT NULL,
    `cesion_id` BIGINT NOT NULL,
    `fecha_detectada` DATETIME(6) NOT NULL,
    `rol_consulta` VARCHAR(20) NOT NULL,
    `fila_origen` INT UNSIGNED NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `rpetc_tarea_cesion_unica` (`tarea_id`, `cesion_id`),
    KEY `rpetc_tarea_cesion_id_idx` (`cesion_id`),
    KEY `rpetc_tarea_rol_idx` (`rol_consulta`),
    CONSTRAINT `rpetc_link_tarea_fk` FOREIGN KEY (`tarea_id`)
        REFERENCES `gestiondte_tarearpetc` (`id`),
    CONSTRAINT `rpetc_link_cesion_fk` FOREIGN KEY (`cesion_id`)
        REFERENCES `gestiondte_cesionrpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_lecturaautomaticaconfig` (
    `id` SMALLINT UNSIGNED NOT NULL,
    `habilitado` TINYINT(1) NOT NULL DEFAULT 0,
    `intervalo_minutos` SMALLINT UNSIGNED NOT NULL DEFAULT 60,
    `ultima_ejecucion` DATETIME(6) NULL,
    `proxima_ejecucion` DATETIME(6) NULL,
    `creado` DATETIME(6) NOT NULL,
    `modificado` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_lecturaautomaticaejecucion` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `lote_id` CHAR(32) NOT NULL,
    `tipo_ejecucion` VARCHAR(12) NOT NULL,
    `fecha_desde` DATE NOT NULL,
    `fecha_hasta` DATE NOT NULL,
    `estado` VARCHAR(15) NOT NULL DEFAULT 'PENDIENTE',
    `progreso` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    `total_documentos` INT UNSIGNED NULL,
    `documentos_procesados` INT UNSIGNED NOT NULL DEFAULT 0,
    `fecha_inicio` DATETIME(6) NULL,
    `fecha_termino` DATETIME(6) NULL,
    `ultima_actualizacion` DATETIME(6) NOT NULL,
    `mensaje_error` LONGTEXT NULL,
    `empresa_id` BIGINT NOT NULL,
    `tarea_rpetc_id` BIGINT NULL,
    PRIMARY KEY (`id`),
    KEY `lectura_auto_lote_estado_idx` (`lote_id`, `estado`),
    KEY `lectura_auto_emp_estado_idx` (`empresa_id`, `estado`),
    KEY `lectura_auto_estado_idx` (`estado`),
    KEY `lectura_auto_lote_idx` (`lote_id`),
    KEY `lectura_auto_empresa_idx` (`empresa_id`),
    KEY `lectura_auto_tarea_idx` (`tarea_rpetc_id`),
    CONSTRAINT `lectura_auto_tarea_fk` FOREIGN KEY (`tarea_rpetc_id`)
        REFERENCES `gestiondte_tarearpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_revisioncesionrpetc` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `empresa_id` BIGINT NOT NULL,
    `cesion_id` BIGINT NOT NULL,
    `glosa` LONGTEXT NOT NULL,
    `creado_por_id` INT NULL,
    `creado_en` DATETIME(6) NOT NULL,
    `modificado_por_id` INT NULL,
    `modificado_en` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `revision_cesion_empresa_unica` (`empresa_id`, `cesion_id`),
    KEY `revision_cesion_emp_idx` (`empresa_id`, `cesion_id`),
    KEY `revision_cesion_empresa_idx` (`empresa_id`),
    KEY `revision_cesion_user_created_idx` (`creado_por_id`),
    KEY `revision_cesion_user_updated_idx` (`modificado_por_id`),
    KEY `revision_cesion_cesion_idx` (`cesion_id`),
    CONSTRAINT `revision_cesion_cesion_fk` FOREIGN KEY (`cesion_id`)
        REFERENCES `gestiondte_cesionrpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_revisioncesioncomentario` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `revision_id` BIGINT NOT NULL,
    `comentario` LONGTEXT NOT NULL,
    `creado_por_id` INT NULL,
    `creado_en` DATETIME(6) NOT NULL,
    `modificado_en` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `revision_comentario_revision_idx` (`revision_id`),
    KEY `revision_comentario_user_idx` (`creado_por_id`),
    CONSTRAINT `revision_comentario_revision_fk` FOREIGN KEY (`revision_id`)
        REFERENCES `gestiondte_revisioncesionrpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `gestiondte_estadocontablecesion` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `empresa_id` BIGINT NOT NULL,
    `cesion_id` BIGINT NOT NULL,
    `estado_contabilizacion` VARCHAR(20) NOT NULL,
    `estado_factoring` VARCHAR(20) NOT NULL,
    `estado_proveedor` VARCHAR(20) NOT NULL,
    `estado_pago_resumen` VARCHAR(20) NOT NULL,
    `fecha_pago_factoring` DATETIME(6) NULL,
    `monto_pago_factoring` DECIMAL(20, 0) NULL,
    `fecha_pago_proveedor` DATETIME(6) NULL,
    `monto_pago_proveedor` DECIMAL(20, 0) NULL,
    `fecha_verificacion` DATETIME(6) NOT NULL,
    `estado_verificacion` VARCHAR(5) NOT NULL DEFAULT 'OK',
    `mensaje_error` VARCHAR(500) NULL,
    `creado` DATETIME(6) NOT NULL,
    `modificado` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `rpetc_estado_empresa_cesion_unico` (`empresa_id`, `cesion_id`),
    KEY `rpetc_estado_emp_pago_idx` (`empresa_id`, `estado_pago_resumen`),
    KEY `rpetc_estado_emp_verif_idx` (`empresa_id`, `fecha_verificacion`),
    KEY `rpetc_estado_cesion_idx` (`cesion_id`),
    CONSTRAINT `rpetc_estado_cesion_fk` FOREIGN KEY (`cesion_id`)
        REFERENCES `gestiondte_cesionrpetc` (`id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
