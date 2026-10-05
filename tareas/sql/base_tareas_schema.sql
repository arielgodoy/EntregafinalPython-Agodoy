-- BASE_TAREAS MYSQL BOOTSTRAP
-- GENERATED FROM DJANGO MODELS/MIGRATIONS
-- DJANGO 5.1.3 / MYSQL SCHEMAEDITOR PREVIEW
-- NO SYSTEM TABLES
-- NO EXTERNAL PHYSICAL FOREIGN KEYS
-- DO NOT EDIT WITHOUT SCHEMA REVIEW

CREATE TABLE IF NOT EXISTS `tareas_tarea` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `titulo` varchar(200) NOT NULL, `descripcion` longtext NOT NULL, `prioridad` varchar(10) NOT NULL, `correlativo` varchar(9) NOT NULL, `anulada` bool NOT NULL, `fechas_pendientes_confirmacion` bool NOT NULL, `cierre_completado` bool NOT NULL, `requiere_evidencia_cierre` bool NOT NULL, `estado` varchar(32) NOT NULL, `responsable_id` integer NULL, `empresa_id` bigint NOT NULL, `tipo_ambito` varchar(12) NULL, `local_id` bigint NULL, `departamento_id` bigint NULL, `creada_por_id` integer NOT NULL, `fecha_creacion` datetime(6) NOT NULL, `fecha_publicacion` datetime(6) NULL, `fecha_asignacion` datetime(6) NULL, `fecha_tope` date NULL, `fecha_cumplimiento` datetime(6) NULL, `todo_origen_id` bigint NULL, `tarea_origen_id` bigint NULL, CONSTRAINT `tareas_empresa_correlativo_uniq` UNIQUE (`empresa_id`, `correlativo`), CONSTRAINT `tareas_unico_origen_canonico` CHECK ((`todo_origen_id` IS NULL OR `tarea_origen_id` IS NULL)), CONSTRAINT `tareas_ambito_xor` CHECK (((`departamento_id` IS NULL AND `local_id` IS NULL AND `tipo_ambito` IS NULL) OR (`departamento_id` IS NULL AND `local_id` IS NULL AND `tipo_ambito` = '') OR (`departamento_id` IS NULL AND `local_id` IS NOT NULL AND `tipo_ambito` = 'LOCAL') OR (`departamento_id` IS NOT NULL AND `local_id` IS NULL AND `tipo_ambito` = 'DEPARTAMENTO'))));

CREATE TABLE IF NOT EXISTS `tareas_evaluacionsimilitud` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `tarea_candidata_id` bigint NOT NULL, `porcentaje` numeric(5, 2) NOT NULL, `umbral_aplicado` numeric(5, 2) NOT NULL, `supera_umbral` bool NOT NULL, `decision` varchar(20) NOT NULL, `confirmada_por_id` integer NULL, `confirmada_at` datetime(6) NULL, `created_at` datetime(6) NOT NULL, CONSTRAINT `unique_evaluacion_similitud_pareja` UNIQUE (`tarea_id`, `tarea_candidata_id`), CONSTRAINT `evaluacion_similitud_tareas_distintas` CHECK (NOT (`tarea_id` = (`tarea_candidata_id`))), CONSTRAINT `evaluacion_similitud_porcentaje_rango` CHECK ((`porcentaje` >= '0' AND `porcentaje` <= '100')), CONSTRAINT `evaluacion_similitud_umbral_rango` CHECK ((`umbral_aplicado` >= '0' AND `umbral_aplicado` <= '100')));

CREATE TABLE IF NOT EXISTS `tareas_umbralsimilitudempresa` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `empresa_id` bigint NOT NULL UNIQUE, `porcentaje` numeric(5, 2) NOT NULL, `actualizado_por_id` integer NOT NULL, `actualizado_at` datetime(6) NOT NULL, CONSTRAINT `umbral_similitud_empresa_porcentaje_rango` CHECK ((`porcentaje` >= '0' AND `porcentaje` <= '100')));

CREATE TABLE IF NOT EXISTS `tareas_reunionrevision` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `empresa_id` bigint NOT NULL, `titulo` varchar(200) NOT NULL, `descripcion` longtext NOT NULL, `fecha_hora_programada` datetime(6) NOT NULL, `modalidad` varchar(10) NOT NULL, `lugar_o_enlace` varchar(500) NULL, `tipo_ambito` varchar(12) NOT NULL, `local_id` bigint NULL, `departamento_id` bigint NULL, `tarea_planificada_id` bigint NOT NULL UNIQUE, `creada_por_id` integer NOT NULL, `estado` varchar(11) NOT NULL, `convocada_at` datetime(6) NULL, `created_at` datetime(6) NOT NULL, `updated_at` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_reuniontarea` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `reunion_id` bigint NOT NULL, `tarea_id` bigint NOT NULL, `orden` integer UNSIGNED NOT NULL CHECK (`orden` >= 0), `comentario_revision` longtext NOT NULL, `comentario_cierre` longtext NOT NULL, `created_at` datetime(6) NOT NULL, CONSTRAINT `unique_reunion_revision_tarea` UNIQUE (`reunion_id`, `tarea_id`), CONSTRAINT `unique_reunion_revision_orden` UNIQUE (`reunion_id`, `orden`));

CREATE TABLE IF NOT EXISTS `tareas_reunionparticipante` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `reunion_id` bigint NOT NULL, `usuario_id` integer NOT NULL, `created_at` datetime(6) NOT NULL, CONSTRAINT `unique_reunion_revision_participante` UNIQUE (`reunion_id`, `usuario_id`));

CREATE TABLE IF NOT EXISTS `tareas_avance` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL UNIQUE, `modo` varchar(10) NOT NULL, `porcentaje` numeric(5, 2) NOT NULL, `fecha_actualizacion` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_hito` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `nombre` varchar(200) NOT NULL, `responsable_id` integer NOT NULL, `anulado` bool NOT NULL, `completado` bool NOT NULL, `completado_por_id` integer NULL, `fecha_completado` datetime(6) NULL, `resena_cierre` longtext NOT NULL, `cumplimiento` numeric(5, 2) NOT NULL, `peso` numeric(7, 2) NOT NULL, `fecha_creacion` datetime(6) NOT NULL, CONSTRAINT `tareas_hito_cumplimiento_rango` CHECK ((`cumplimiento` >= '0' AND `cumplimiento` <= '100')), CONSTRAINT `tareas_hito_peso_positivo` CHECK (`peso` > '0'));

CREATE TABLE IF NOT EXISTS `tareas_hitohistorial` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `hito_id` bigint NOT NULL, `tipo_evento` varchar(32) NOT NULL, `usuario_id` integer NULL, `fecha` datetime(6) NOT NULL, `datos_anteriores` json NOT NULL, `datos_nuevos` json NOT NULL, `motivo` longtext NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_hitoevidencia` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `hito_id` bigint NOT NULL, `formato_archivo` varchar(4) NOT NULL, `archivo` varchar(100) NOT NULL, `url` varchar(200) NOT NULL, `usuario_id` integer NOT NULL, `fecha` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_minitarea` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `descripcion` varchar(200) NOT NULL, `persona_id` integer NOT NULL, `hecho` bool NOT NULL, `fecha_creacion` datetime(6) NOT NULL, `fecha_completado` datetime(6) NULL);

CREATE TABLE IF NOT EXISTS `tareas_minitareaevento` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `mini_tarea_id` bigint NOT NULL, `comentario_feed_id` bigint NULL UNIQUE, `tipo` varchar(12) NOT NULL, `actor_id` integer NOT NULL, `fecha` datetime(6) NOT NULL, `comentario` longtext NOT NULL, `destinatarios_notificacion` json NOT NULL, `destinatarios_email` json NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_documentotarea` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `tipo` varchar(20) NOT NULL, `formato_archivo` varchar(4) NOT NULL, `archivo` varchar(100) NOT NULL, `url` varchar(200) NOT NULL, `fecha_documento` date NOT NULL, `fecha_vencimiento` date NULL, `usuario_id` integer NOT NULL, `estado` varchar(20) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_documentohistorial` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `documento_id` bigint NOT NULL, `accion` varchar(20) NOT NULL, `usuario_id` integer NOT NULL, `fecha` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_evidenciacierre` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `documento_id` bigint NULL, `formato_archivo` varchar(4) NOT NULL, `archivo` varchar(100) NOT NULL, `url` varchar(200) NOT NULL, `usuario_id` integer NOT NULL, `fecha` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_correlativoempresa` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `empresa_id` bigint NOT NULL UNIQUE, `siguiente_numero` integer UNSIGNED NOT NULL CHECK (`siguiente_numero` >= 0));

CREATE TABLE IF NOT EXISTS `tareas_correlativotodoempresa` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `empresa_id` bigint NOT NULL UNIQUE, `siguiente_numero` integer UNSIGNED NOT NULL CHECK (`siguiente_numero` >= 0));

CREATE TABLE IF NOT EXISTS `tareas_todo` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `empresa_id` bigint NOT NULL, `correlativo` varchar(9) NOT NULL, `titulo` varchar(200) NOT NULL, `descripcion` longtext NOT NULL, `estado` varchar(8) NOT NULL, `creada_por_id` integer NOT NULL, `fecha_creacion` datetime(6) NOT NULL, `cerrada_por_id` integer NULL, `fecha_cierre` datetime(6) NULL, `comentario_cierre` longtext NOT NULL, `todo_anterior_id` bigint NULL, CONSTRAINT `tareas_empresa_todo_correlativo_uniq` UNIQUE (`empresa_id`, `correlativo`));

CREATE TABLE IF NOT EXISTS `tareas_todoevento` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `todo_id` bigint NOT NULL, `tipo` varchar(20) NOT NULL, `usuario_id` integer NOT NULL, `timestamp` datetime(6) NOT NULL, `comentario` longtext NOT NULL, `tarea_id` bigint NULL);

CREATE TABLE IF NOT EXISTS `tareas_tareatransicion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `estado_origen` varchar(32) NOT NULL, `estado_destino` varchar(32) NOT NULL, `accion_evento` varchar(64) NOT NULL, `usuario_id` integer NOT NULL, `timestamp` datetime(6) NOT NULL, `motivo` longtext NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_tareacierre` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `usuario_id` integer NOT NULL, `timestamp` datetime(6) NOT NULL, `resultado` varchar(10) NOT NULL, `comentario` longtext NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_tareaanulacionsnapshot` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `estado_anterior` varchar(32) NOT NULL, `fechas_pendientes_confirmacion` bool NOT NULL, `usuario_anulo_id` integer NOT NULL, `timestamp_anulacion` datetime(6) NOT NULL, `usuario_reactivo_id` integer NULL, `timestamp_reactivacion` datetime(6) NULL);

CREATE TABLE IF NOT EXISTS `tareas_tareaparticipante` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `usuario_id` integer NOT NULL, `rol` varchar(32) NOT NULL, `fecha` datetime(6) NOT NULL, CONSTRAINT `tareas_participante_unico_por_tarea` UNIQUE (`tarea_id`, `usuario_id`));

CREATE TABLE IF NOT EXISTS `tareas_tarealectura` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `usuario_id` integer NOT NULL, `leido` bool NOT NULL, `fecha_lectura` datetime(6) NULL, `comentario_leido_hasta_id` bigint NULL, CONSTRAINT `tareas_lectura_unica_por_usuario` UNIQUE (`tarea_id`, `usuario_id`));

CREATE TABLE IF NOT EXISTS `tareas_comentario` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `autor_id` integer NOT NULL, `contenido` longtext NOT NULL, `created_at` datetime(6) NOT NULL, `updated_at` datetime(6) NOT NULL, `oculto` bool NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_comentarioadjunto` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `comentario_id` bigint NOT NULL, `documento_id` bigint NOT NULL, CONSTRAINT `tareas_com_adjunto_unico` UNIQUE (`comentario_id`, `documento_id`));

CREATE TABLE IF NOT EXISTS `tareas_comentarioversion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `comentario_id` bigint NOT NULL, `evento` varchar(10) NOT NULL, `numero_version` integer UNSIGNED NULL CHECK (`numero_version` >= 0), `contenido` longtext NOT NULL, `actor_id` integer NOT NULL, `fecha` datetime(6) NOT NULL, `motivo` longtext NOT NULL, CONSTRAINT `tareas_com_version_unica` UNIQUE (`comentario_id`, `numero_version`));

CREATE TABLE IF NOT EXISTS `tareas_comentarioversiondocumento` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `version_id` bigint NOT NULL, `documento_id` bigint NOT NULL, CONSTRAINT `tareas_com_ver_doc_unico` UNIQUE (`version_id`, `documento_id`));

CREATE TABLE IF NOT EXISTS `tareas_comentariopausalectura` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `lectura_id` bigint NOT NULL, `desde` datetime(6) NOT NULL, `hasta` datetime(6) NULL, CONSTRAINT `tareas_com_pausa_intervalo` CHECK ((`hasta` IS NULL OR `hasta` >= (`desde`))));

CREATE TABLE IF NOT EXISTS `tareas_enlacetarea` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `destinatario_id` integer NOT NULL, `creado_por_id` integer NOT NULL, `token_hash` varchar(64) NOT NULL UNIQUE, `fecha_creacion` datetime(6) NOT NULL, `fecha_expiracion` datetime(6) NOT NULL, `revocado_at` datetime(6) NULL, `revocado_por_id` integer NULL);

CREATE TABLE IF NOT EXISTS `tareas_eventoaccesoenlace` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `enlace_id` bigint NOT NULL, `usuario_id` integer NULL, `fecha` datetime(6) NOT NULL, `resultado` varchar(24) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_tareareasignacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `responsable_anterior_id` integer NULL, `responsable_nuevo_id` integer NOT NULL, `usuario_id` integer NOT NULL, `fecha` datetime(6) NOT NULL, `motivo` longtext NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_causaatraso` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `codigo` varchar(40) NOT NULL UNIQUE, `nombre` varchar(120) NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS `tareas_reprogramacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `fecha_tope_anterior` date NOT NULL, `fecha_tope_nueva` date NOT NULL, `justificacion` longtext NOT NULL, `usuario_id` integer NOT NULL, `fecha_operacion` datetime(6) NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_reprogramacion_causas` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `reprogramacion_id` bigint NOT NULL, `causaatraso_id` bigint NOT NULL);

CREATE TABLE IF NOT EXISTS `tareas_tarearelacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `padre_id` bigint NOT NULL, `hija_id` bigint NOT NULL, `fecha` datetime(6) NOT NULL, CONSTRAINT `tareas_relacion_hija_unico_padre` UNIQUE (`hija_id`));

CREATE TABLE IF NOT EXISTS `tareas_rondacotizacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `tarea_id` bigint NOT NULL, `numero` integer UNSIGNED NOT NULL CHECK (`numero` >= 0), `minimo_cotizaciones` integer UNSIGNED NOT NULL CHECK (`minimo_cotizaciones` >= 0), `estado` varchar(8) NOT NULL, `fecha_apertura` datetime(6) NOT NULL, `fecha_cierre` datetime(6) NULL, CONSTRAINT `tareas_ronda_tarea_numero_unico` UNIQUE (`tarea_id`, `numero`), CONSTRAINT `tareas_ronda_numero_positivo` CHECK (`numero` >= 1), CONSTRAINT `tareas_ronda_minimo_positivo` CHECK (`minimo_cotizaciones` >= 1));

CREATE TABLE IF NOT EXISTS `tareas_cotizacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `ronda_id` bigint NOT NULL, `proveedor_id` bigint NULL, `version` integer UNSIGNED NOT NULL CHECK (`version` >= 0), `monto` numeric(12, 2) NOT NULL, `vigente` bool NOT NULL, `estado` varchar(13) NOT NULL, `fecha_cotizacion` date NOT NULL, `observaciones` longtext NOT NULL, CONSTRAINT `tareas_cotizacion_version_positiva` CHECK (`version` >= 1), CONSTRAINT `tareas_cotizacion_monto_no_negativo` CHECK (`monto` >= '0'));

CREATE TABLE IF NOT EXISTS `tareas_documentocotizacion` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `cotizacion_id` bigint NOT NULL, `formato_archivo` varchar(4) NOT NULL, `archivo` varchar(100) NOT NULL, `url` varchar(200) NOT NULL, `usuario_id` integer NOT NULL, `fecha` datetime(6) NOT NULL);

ALTER TABLE `tareas_tarea` ADD CONSTRAINT `tareas_tarea_todo_origen_id_5ede95b3_fk_tareas_todo_id` FOREIGN KEY (`todo_origen_id`) REFERENCES `tareas_todo` (`id`);

ALTER TABLE `tareas_tarea` ADD CONSTRAINT `tareas_tarea_tarea_origen_id_c173a9ed_fk_tareas_tarea_id` FOREIGN KEY (`tarea_origen_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tarea_responsable_id_d2268bab` ON `tareas_tarea` (`responsable_id`);

CREATE INDEX `tareas_tarea_empresa_id_97a4d75d` ON `tareas_tarea` (`empresa_id`);

CREATE INDEX `tareas_tarea_local_id_6b27e6d7` ON `tareas_tarea` (`local_id`);

CREATE INDEX `tareas_tarea_departamento_id_d804ed4f` ON `tareas_tarea` (`departamento_id`);

CREATE INDEX `tareas_tarea_creada_por_id_52723310` ON `tareas_tarea` (`creada_por_id`);

CREATE INDEX `tareas_tarea_todo_origen_id_5ede95b3` ON `tareas_tarea` (`todo_origen_id`);

CREATE INDEX `tareas_tarea_tarea_origen_id_c173a9ed` ON `tareas_tarea` (`tarea_origen_id`);

CREATE INDEX `tareas_tare_empresa_f82081_idx` ON `tareas_tarea` (`empresa_id`, `estado`);

CREATE INDEX `tareas_tare_empresa_8defd5_idx` ON `tareas_tarea` (`empresa_id`, `fecha_creacion`);

CREATE INDEX `tareas_tare_empresa_e8cfb3_idx` ON `tareas_tarea` (`empresa_id`, `correlativo`);

ALTER TABLE `tareas_evaluacionsimilitud` ADD CONSTRAINT `tareas_evaluacionsimilitud_tarea_id_7e6f7200_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

ALTER TABLE `tareas_evaluacionsimilitud` ADD CONSTRAINT `tareas_evaluacionsim_tarea_candidata_id_776c2407_fk_tareas_ta` FOREIGN KEY (`tarea_candidata_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_evaluacionsimilitud_tarea_id_7e6f7200` ON `tareas_evaluacionsimilitud` (`tarea_id`);

CREATE INDEX `tareas_evaluacionsimilitud_tarea_candidata_id_776c2407` ON `tareas_evaluacionsimilitud` (`tarea_candidata_id`);

CREATE INDEX `tareas_evaluacionsimilitud_confirmada_por_id_bafb421f` ON `tareas_evaluacionsimilitud` (`confirmada_por_id`);

CREATE INDEX `tareas_umbralsimilitudempresa_actualizado_por_id_61693c22` ON `tareas_umbralsimilitudempresa` (`actualizado_por_id`);

ALTER TABLE `tareas_reunionrevision` ADD CONSTRAINT `tareas_reunionrevisi_tarea_planificada_id_1fa5f8a3_fk_tareas_ta` FOREIGN KEY (`tarea_planificada_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_reunionrevision_empresa_id_0c1a4c5d` ON `tareas_reunionrevision` (`empresa_id`);

CREATE INDEX `tareas_reunionrevision_local_id_1806851d` ON `tareas_reunionrevision` (`local_id`);

CREATE INDEX `tareas_reunionrevision_departamento_id_83720930` ON `tareas_reunionrevision` (`departamento_id`);

CREATE INDEX `tareas_reunionrevision_creada_por_id_7cb94eb0` ON `tareas_reunionrevision` (`creada_por_id`);

ALTER TABLE `tareas_reuniontarea` ADD CONSTRAINT `tareas_reuniontarea_reunion_id_d42a5f05_fk_tareas_re` FOREIGN KEY (`reunion_id`) REFERENCES `tareas_reunionrevision` (`id`);

ALTER TABLE `tareas_reuniontarea` ADD CONSTRAINT `tareas_reuniontarea_tarea_id_e927b06b_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_reuniontarea_reunion_id_d42a5f05` ON `tareas_reuniontarea` (`reunion_id`);

CREATE INDEX `tareas_reuniontarea_tarea_id_e927b06b` ON `tareas_reuniontarea` (`tarea_id`);

ALTER TABLE `tareas_reunionparticipante` ADD CONSTRAINT `tareas_reunionpartic_reunion_id_e0df5f0d_fk_tareas_re` FOREIGN KEY (`reunion_id`) REFERENCES `tareas_reunionrevision` (`id`);

CREATE INDEX `tareas_reunionparticipante_reunion_id_e0df5f0d` ON `tareas_reunionparticipante` (`reunion_id`);

CREATE INDEX `tareas_reunionparticipante_usuario_id_b916cc6f` ON `tareas_reunionparticipante` (`usuario_id`);

ALTER TABLE `tareas_avance` ADD CONSTRAINT `tareas_avance_tarea_id_2862949f_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

ALTER TABLE `tareas_hito` ADD CONSTRAINT `tareas_hito_tarea_id_79cee7e4_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_hito_tarea_id_79cee7e4` ON `tareas_hito` (`tarea_id`);

CREATE INDEX `tareas_hito_responsable_id_8b354c8f` ON `tareas_hito` (`responsable_id`);

CREATE INDEX `tareas_hito_completado_por_id_7e4ea2a4` ON `tareas_hito` (`completado_por_id`);

ALTER TABLE `tareas_hitohistorial` ADD CONSTRAINT `tareas_hitohistorial_hito_id_0c288d0e_fk_tareas_hito_id` FOREIGN KEY (`hito_id`) REFERENCES `tareas_hito` (`id`);

CREATE INDEX `tareas_hitohistorial_hito_id_0c288d0e` ON `tareas_hitohistorial` (`hito_id`);

CREATE INDEX `tareas_hitohistorial_usuario_id_10b6d68d` ON `tareas_hitohistorial` (`usuario_id`);

CREATE INDEX `tareas_hh_hito_fecha_idx` ON `tareas_hitohistorial` (`hito_id`, `fecha`);

ALTER TABLE `tareas_hitoevidencia` ADD CONSTRAINT `tareas_hitoevidencia_hito_id_3a70c275_fk_tareas_hito_id` FOREIGN KEY (`hito_id`) REFERENCES `tareas_hito` (`id`);

CREATE INDEX `tareas_hitoevidencia_hito_id_3a70c275` ON `tareas_hitoevidencia` (`hito_id`);

CREATE INDEX `tareas_hitoevidencia_usuario_id_2957d544` ON `tareas_hitoevidencia` (`usuario_id`);

CREATE INDEX `tareas_he_hito_fecha_idx` ON `tareas_hitoevidencia` (`hito_id`, `fecha`);

ALTER TABLE `tareas_minitarea` ADD CONSTRAINT `tareas_minitarea_tarea_id_52bd4952_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_minitarea_tarea_id_52bd4952` ON `tareas_minitarea` (`tarea_id`);

CREATE INDEX `tareas_minitarea_persona_id_afec4cb4` ON `tareas_minitarea` (`persona_id`);

CREATE INDEX `tareas_mini_tarea_i_657b89_idx` ON `tareas_minitarea` (`tarea_id`, `hecho`);

ALTER TABLE `tareas_minitareaevento` ADD CONSTRAINT `tareas_minitareaeven_mini_tarea_id_534964e5_fk_tareas_mi` FOREIGN KEY (`mini_tarea_id`) REFERENCES `tareas_minitarea` (`id`);

ALTER TABLE `tareas_minitareaevento` ADD CONSTRAINT `tareas_minitareaeven_comentario_feed_id_df24f502_fk_tareas_co` FOREIGN KEY (`comentario_feed_id`) REFERENCES `tareas_comentario` (`id`);

CREATE INDEX `tareas_minitareaevento_mini_tarea_id_534964e5` ON `tareas_minitareaevento` (`mini_tarea_id`);

CREATE INDEX `tareas_minitareaevento_actor_id_53e1b2e5` ON `tareas_minitareaevento` (`actor_id`);

CREATE INDEX `tareas_mini_mini_ta_288ed4_idx` ON `tareas_minitareaevento` (`mini_tarea_id`, `fecha`);

ALTER TABLE `tareas_documentotarea` ADD CONSTRAINT `tareas_documentotarea_tarea_id_04512147_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_documentotarea_tarea_id_04512147` ON `tareas_documentotarea` (`tarea_id`);

CREATE INDEX `tareas_documentotarea_usuario_id_cd18f886` ON `tareas_documentotarea` (`usuario_id`);

CREATE INDEX `tareas_docu_tarea_i_9efff0_idx` ON `tareas_documentotarea` (`tarea_id`, `tipo`);

CREATE INDEX `tareas_docu_tarea_i_54596b_idx` ON `tareas_documentotarea` (`tarea_id`, `estado`);

ALTER TABLE `tareas_documentohistorial` ADD CONSTRAINT `tareas_documentohist_documento_id_07ec5b51_fk_tareas_do` FOREIGN KEY (`documento_id`) REFERENCES `tareas_documentotarea` (`id`);

CREATE INDEX `tareas_documentohistorial_documento_id_07ec5b51` ON `tareas_documentohistorial` (`documento_id`);

CREATE INDEX `tareas_documentohistorial_usuario_id_4d2d242e` ON `tareas_documentohistorial` (`usuario_id`);

CREATE INDEX `tareas_docu_documen_236103_idx` ON `tareas_documentohistorial` (`documento_id`, `fecha`);

ALTER TABLE `tareas_evidenciacierre` ADD CONSTRAINT `tareas_evidenciacierre_tarea_id_2e5cd9d8_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

ALTER TABLE `tareas_evidenciacierre` ADD CONSTRAINT `tareas_evidenciacier_documento_id_939af3fd_fk_tareas_do` FOREIGN KEY (`documento_id`) REFERENCES `tareas_documentotarea` (`id`);

CREATE INDEX `tareas_evidenciacierre_tarea_id_2e5cd9d8` ON `tareas_evidenciacierre` (`tarea_id`);

CREATE INDEX `tareas_evidenciacierre_documento_id_939af3fd` ON `tareas_evidenciacierre` (`documento_id`);

CREATE INDEX `tareas_evidenciacierre_usuario_id_0acc10ed` ON `tareas_evidenciacierre` (`usuario_id`);

CREATE INDEX `tareas_evid_tarea_fecha_idx` ON `tareas_evidenciacierre` (`tarea_id`, `fecha`);

CREATE INDEX `tareas_corr_empresa_322dab_idx` ON `tareas_correlativoempresa` (`empresa_id`);

CREATE INDEX `tareas_corr_empresa_ef5395_idx` ON `tareas_correlativotodoempresa` (`empresa_id`);

ALTER TABLE `tareas_todo` ADD CONSTRAINT `tareas_todo_todo_anterior_id_7519e59a_fk_tareas_todo_id` FOREIGN KEY (`todo_anterior_id`) REFERENCES `tareas_todo` (`id`);

CREATE INDEX `tareas_todo_empresa_id_74433959` ON `tareas_todo` (`empresa_id`);

CREATE INDEX `tareas_todo_creada_por_id_2fb73bcf` ON `tareas_todo` (`creada_por_id`);

CREATE INDEX `tareas_todo_cerrada_por_id_b0b46b04` ON `tareas_todo` (`cerrada_por_id`);

CREATE INDEX `tareas_todo_todo_anterior_id_7519e59a` ON `tareas_todo` (`todo_anterior_id`);

CREATE INDEX `tareas_todo_empresa_dab7f2_idx` ON `tareas_todo` (`empresa_id`, `estado`);

CREATE INDEX `tareas_todo_empresa_5f6d14_idx` ON `tareas_todo` (`empresa_id`, `fecha_creacion`);

ALTER TABLE `tareas_todoevento` ADD CONSTRAINT `tareas_todoevento_todo_id_dd96bbac_fk_tareas_todo_id` FOREIGN KEY (`todo_id`) REFERENCES `tareas_todo` (`id`);

ALTER TABLE `tareas_todoevento` ADD CONSTRAINT `tareas_todoevento_tarea_id_adac2bdb_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_todoevento_todo_id_dd96bbac` ON `tareas_todoevento` (`todo_id`);

CREATE INDEX `tareas_todoevento_usuario_id_de29ab76` ON `tareas_todoevento` (`usuario_id`);

CREATE INDEX `tareas_todoevento_tarea_id_adac2bdb` ON `tareas_todoevento` (`tarea_id`);

CREATE INDEX `tareas_todo_todo_id_222afd_idx` ON `tareas_todoevento` (`todo_id`, `timestamp`);

ALTER TABLE `tareas_tareatransicion` ADD CONSTRAINT `tareas_tareatransicion_tarea_id_5d426ffd_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tareatransicion_tarea_id_5d426ffd` ON `tareas_tareatransicion` (`tarea_id`);

CREATE INDEX `tareas_tareatransicion_usuario_id_eae0b6a3` ON `tareas_tareatransicion` (`usuario_id`);

CREATE INDEX `tareas_tare_tarea_i_78e961_idx` ON `tareas_tareatransicion` (`tarea_id`, `timestamp`);

ALTER TABLE `tareas_tareacierre` ADD CONSTRAINT `tareas_tareacierre_tarea_id_dbc34467_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tareacierre_tarea_id_dbc34467` ON `tareas_tareacierre` (`tarea_id`);

CREATE INDEX `tareas_tareacierre_usuario_id_b4119d1a` ON `tareas_tareacierre` (`usuario_id`);

ALTER TABLE `tareas_tareaanulacionsnapshot` ADD CONSTRAINT `tareas_tareaanulacio_tarea_id_5e78d5d9_fk_tareas_ta` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tareaanulacionsnapshot_tarea_id_5e78d5d9` ON `tareas_tareaanulacionsnapshot` (`tarea_id`);

CREATE INDEX `tareas_tareaanulacionsnapshot_usuario_anulo_id_891fefb7` ON `tareas_tareaanulacionsnapshot` (`usuario_anulo_id`);

CREATE INDEX `tareas_tareaanulacionsnapshot_usuario_reactivo_id_54faba11` ON `tareas_tareaanulacionsnapshot` (`usuario_reactivo_id`);

ALTER TABLE `tareas_tareaparticipante` ADD CONSTRAINT `tareas_tareaparticipante_tarea_id_6d066ebc_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tareaparticipante_tarea_id_6d066ebc` ON `tareas_tareaparticipante` (`tarea_id`);

CREATE INDEX `tareas_tareaparticipante_usuario_id_3493f890` ON `tareas_tareaparticipante` (`usuario_id`);

CREATE INDEX `tareas_tare_tarea_i_003772_idx` ON `tareas_tareaparticipante` (`tarea_id`, `usuario_id`);

ALTER TABLE `tareas_tarealectura` ADD CONSTRAINT `tareas_tarealectura_tarea_id_1861aa97_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

ALTER TABLE `tareas_tarealectura` ADD CONSTRAINT `tareas_tarealectura_comentario_leido_has_5596ea5c_fk_tareas_co` FOREIGN KEY (`comentario_leido_hasta_id`) REFERENCES `tareas_comentario` (`id`);

CREATE INDEX `tareas_tarealectura_tarea_id_1861aa97` ON `tareas_tarealectura` (`tarea_id`);

CREATE INDEX `tareas_tarealectura_usuario_id_5321e203` ON `tareas_tarealectura` (`usuario_id`);

CREATE INDEX `tareas_tarealectura_comentario_leido_hasta_id_5596ea5c` ON `tareas_tarealectura` (`comentario_leido_hasta_id`);

CREATE INDEX `tareas_tare_tarea_i_cf4777_idx` ON `tareas_tarealectura` (`tarea_id`, `usuario_id`, `leido`);

ALTER TABLE `tareas_comentario` ADD CONSTRAINT `tareas_comentario_tarea_id_ce4c7b1c_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_comentario_tarea_id_ce4c7b1c` ON `tareas_comentario` (`tarea_id`);

CREATE INDEX `tareas_comentario_autor_id_39dcee2d` ON `tareas_comentario` (`autor_id`);

CREATE INDEX `tareas_come_tarea_i_d9a726_idx` ON `tareas_comentario` (`tarea_id`, `created_at`, `id`);

ALTER TABLE `tareas_comentarioadjunto` ADD CONSTRAINT `tareas_comentarioadj_comentario_id_df9ad742_fk_tareas_co` FOREIGN KEY (`comentario_id`) REFERENCES `tareas_comentario` (`id`);

ALTER TABLE `tareas_comentarioadjunto` ADD CONSTRAINT `tareas_comentarioadj_documento_id_cbb22438_fk_tareas_do` FOREIGN KEY (`documento_id`) REFERENCES `tareas_documentotarea` (`id`);

CREATE INDEX `tareas_comentarioadjunto_comentario_id_df9ad742` ON `tareas_comentarioadjunto` (`comentario_id`);

CREATE INDEX `tareas_comentarioadjunto_documento_id_cbb22438` ON `tareas_comentarioadjunto` (`documento_id`);

ALTER TABLE `tareas_comentarioversion` ADD CONSTRAINT `tareas_comentariover_comentario_id_af3f908a_fk_tareas_co` FOREIGN KEY (`comentario_id`) REFERENCES `tareas_comentario` (`id`);

CREATE INDEX `tareas_comentarioversion_comentario_id_af3f908a` ON `tareas_comentarioversion` (`comentario_id`);

CREATE INDEX `tareas_comentarioversion_actor_id_1ee74245` ON `tareas_comentarioversion` (`actor_id`);

CREATE INDEX `tareas_come_comenta_0c6900_idx` ON `tareas_comentarioversion` (`comentario_id`, `fecha`, `id`);

ALTER TABLE `tareas_comentarioversiondocumento` ADD CONSTRAINT `tareas_comentariover_version_id_1b493594_fk_tareas_co` FOREIGN KEY (`version_id`) REFERENCES `tareas_comentarioversion` (`id`);

ALTER TABLE `tareas_comentarioversiondocumento` ADD CONSTRAINT `tareas_comentariover_documento_id_9104bf32_fk_tareas_do` FOREIGN KEY (`documento_id`) REFERENCES `tareas_documentotarea` (`id`);

CREATE INDEX `tareas_comentarioversiondocumento_version_id_1b493594` ON `tareas_comentarioversiondocumento` (`version_id`);

CREATE INDEX `tareas_comentarioversiondocumento_documento_id_9104bf32` ON `tareas_comentarioversiondocumento` (`documento_id`);

ALTER TABLE `tareas_comentariopausalectura` ADD CONSTRAINT `tareas_comentariopau_lectura_id_d6848bea_fk_tareas_ta` FOREIGN KEY (`lectura_id`) REFERENCES `tareas_tarealectura` (`id`);

CREATE INDEX `tareas_comentariopausalectura_lectura_id_d6848bea` ON `tareas_comentariopausalectura` (`lectura_id`);

CREATE INDEX `tareas_come_lectura_d36bd6_idx` ON `tareas_comentariopausalectura` (`lectura_id`, `desde`);

ALTER TABLE `tareas_enlacetarea` ADD CONSTRAINT `tareas_enlacetarea_tarea_id_8ae37d48_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_enlacetarea_tarea_id_8ae37d48` ON `tareas_enlacetarea` (`tarea_id`);

CREATE INDEX `tareas_enlacetarea_destinatario_id_65929d60` ON `tareas_enlacetarea` (`destinatario_id`);

CREATE INDEX `tareas_enlacetarea_creado_por_id_4bbd56ef` ON `tareas_enlacetarea` (`creado_por_id`);

CREATE INDEX `tareas_enlacetarea_revocado_por_id_95d093e2` ON `tareas_enlacetarea` (`revocado_por_id`);

ALTER TABLE `tareas_eventoaccesoenlace` ADD CONSTRAINT `tareas_eventoaccesoe_enlace_id_f2fe03d4_fk_tareas_en` FOREIGN KEY (`enlace_id`) REFERENCES `tareas_enlacetarea` (`id`);

CREATE INDEX `tareas_eventoaccesoenlace_enlace_id_f2fe03d4` ON `tareas_eventoaccesoenlace` (`enlace_id`);

CREATE INDEX `tareas_eventoaccesoenlace_usuario_id_bbcdaeae` ON `tareas_eventoaccesoenlace` (`usuario_id`);

ALTER TABLE `tareas_tareareasignacion` ADD CONSTRAINT `tareas_tareareasignacion_tarea_id_037817eb_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tareareasignacion_tarea_id_037817eb` ON `tareas_tareareasignacion` (`tarea_id`);

CREATE INDEX `tareas_tareareasignacion_responsable_anterior_id_0c4227b2` ON `tareas_tareareasignacion` (`responsable_anterior_id`);

CREATE INDEX `tareas_tareareasignacion_responsable_nuevo_id_beef98e7` ON `tareas_tareareasignacion` (`responsable_nuevo_id`);

CREATE INDEX `tareas_tareareasignacion_usuario_id_c2604901` ON `tareas_tareareasignacion` (`usuario_id`);

CREATE INDEX `tareas_tare_tarea_i_bce944_idx` ON `tareas_tareareasignacion` (`tarea_id`, `fecha`);

ALTER TABLE `tareas_reprogramacion` ADD CONSTRAINT `tareas_reprogramacion_tarea_id_f32df56c_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_reprogramacion_tarea_id_f32df56c` ON `tareas_reprogramacion` (`tarea_id`);

CREATE INDEX `tareas_reprogramacion_usuario_id_e8e45e07` ON `tareas_reprogramacion` (`usuario_id`);

CREATE INDEX `tareas_repr_tarea_i_f8d80e_idx` ON `tareas_reprogramacion` (`tarea_id`, `fecha_operacion`);

ALTER TABLE `tareas_reprogramacion_causas` ADD CONSTRAINT `tareas_reprogramacion_ca_reprogramacion_id_causaa_122589bf_uniq` UNIQUE (`reprogramacion_id`, `causaatraso_id`);

ALTER TABLE `tareas_reprogramacion_causas` ADD CONSTRAINT `tareas_reprogramacio_reprogramacion_id_75e3656c_fk_tareas_re` FOREIGN KEY (`reprogramacion_id`) REFERENCES `tareas_reprogramacion` (`id`);

ALTER TABLE `tareas_reprogramacion_causas` ADD CONSTRAINT `tareas_reprogramacio_causaatraso_id_67382b78_fk_tareas_ca` FOREIGN KEY (`causaatraso_id`) REFERENCES `tareas_causaatraso` (`id`);

CREATE INDEX `tareas_reprogramacion_causas_reprogramacion_id_75e3656c` ON `tareas_reprogramacion_causas` (`reprogramacion_id`);

CREATE INDEX `tareas_reprogramacion_causas_causaatraso_id_67382b78` ON `tareas_reprogramacion_causas` (`causaatraso_id`);

ALTER TABLE `tareas_tarearelacion` ADD CONSTRAINT `tareas_tarearelacion_padre_id_2794eb73_fk_tareas_tarea_id` FOREIGN KEY (`padre_id`) REFERENCES `tareas_tarea` (`id`);

ALTER TABLE `tareas_tarearelacion` ADD CONSTRAINT `tareas_tarearelacion_hija_id_440d734c_fk_tareas_tarea_id` FOREIGN KEY (`hija_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_tarearelacion_padre_id_2794eb73` ON `tareas_tarearelacion` (`padre_id`);

CREATE INDEX `tareas_tarearelacion_hija_id_440d734c` ON `tareas_tarearelacion` (`hija_id`);

CREATE INDEX `tareas_tare_padre_i_941c9c_idx` ON `tareas_tarearelacion` (`padre_id`);

CREATE INDEX `tareas_tare_hija_id_39eace_idx` ON `tareas_tarearelacion` (`hija_id`);

ALTER TABLE `tareas_rondacotizacion` ADD CONSTRAINT `tareas_rondacotizacion_tarea_id_d9400e50_fk_tareas_tarea_id` FOREIGN KEY (`tarea_id`) REFERENCES `tareas_tarea` (`id`);

CREATE INDEX `tareas_rondacotizacion_tarea_id_d9400e50` ON `tareas_rondacotizacion` (`tarea_id`);

CREATE INDEX `tareas_rond_tarea_i_41f0c3_idx` ON `tareas_rondacotizacion` (`tarea_id`, `estado`);

ALTER TABLE `tareas_cotizacion` ADD CONSTRAINT `tareas_cotizacion_ronda_id_e853ae75_fk_tareas_rondacotizacion_id` FOREIGN KEY (`ronda_id`) REFERENCES `tareas_rondacotizacion` (`id`);

CREATE INDEX `tareas_cotizacion_ronda_id_e853ae75` ON `tareas_cotizacion` (`ronda_id`);

CREATE INDEX `tareas_cotizacion_proveedor_id_9e4def47` ON `tareas_cotizacion` (`proveedor_id`);

CREATE INDEX `tareas_coti_ronda_i_7fbd4a_idx` ON `tareas_cotizacion` (`ronda_id`, `estado`);

ALTER TABLE `tareas_documentocotizacion` ADD CONSTRAINT `tareas_documentocoti_cotizacion_id_731fb67f_fk_tareas_co` FOREIGN KEY (`cotizacion_id`) REFERENCES `tareas_cotizacion` (`id`);

CREATE INDEX `tareas_documentocotizacion_cotizacion_id_731fb67f` ON `tareas_documentocotizacion` (`cotizacion_id`);

CREATE INDEX `tareas_documentocotizacion_usuario_id_08fe3648` ON `tareas_documentocotizacion` (`usuario_id`);

CREATE INDEX `tareas_docu_cotizac_ee3db1_idx` ON `tareas_documentocotizacion` (`cotizacion_id`, `fecha`);
