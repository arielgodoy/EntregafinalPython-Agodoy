CREATE TABLE IF NOT EXISTS `gestiondte_certificadosii` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `empresa_codigo` VARCHAR(10) NOT NULL,
    `archivo` VARCHAR(100) NOT NULL,
    `password_encrypted` BLOB NULL,
    `activo` TINYINT(1) NOT NULL DEFAULT 0,
    `titular` VARCHAR(255) NULL,
    `emisor_certificado` VARCHAR(255) NULL,
    `numero_serie` VARCHAR(255) NULL,
    `rut_titular` VARCHAR(64) NULL,
    `valido_desde` DATETIME(6) NULL,
    `valido_hasta` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `gestiondte_cert_empresa_idx` (`empresa_codigo`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
