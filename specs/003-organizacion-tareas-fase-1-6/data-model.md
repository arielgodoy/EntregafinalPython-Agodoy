# Modelo de datos propuesto Fase 1.6

**Estado**: diseno, NO modelos/migraciones generados ni aplicados.
Referencias: [spec](spec.md), [consistencia](contracts/consistencia.md).
Los nombres de entidades nuevas son propuestas tecnicas locales; no agregan roles
ni permisos de negocio.

## Entidades existentes que se preservan

| Entidad / owner | Identidad, relaciones y restricciones |
|---|---|
| User / Django-acounts | Identidad canónica; actividad y acceso Empresa consultados por interfaces SYSTEM |
| Empresa / access_control | PK canónica, nunca se sustituye por Empresa enviada por formulario |
| Local / organizacion | PK interna; Empresa PROTECT; codigo(100) unico por Empresa; nombre(255); legacy_code(100) nullable; activo; source ERP/LOCAL; created_at/updated_at |
| Departamento / organizacion | Misma estructura anterior salvo legacy_code; no FK a Local |
| Tarea / tareas | Identidad y Empresa actuales; ambito LOCAL/DEPARTAMENTO o historico vacio; local_id/departamento_id XOR; historia cerrada preservada |
| TareaParticipante / tareas | Unico (tarea, usuario), rol historico; no contiene membresia organizacional |
| TareaReasignacion / tareas | Ledger existente para responsable; conservar filas e identidad saliente |

Organizacion se mantiene en `default` con sus referencias canónicas locales. El
router no fuerza una base especial para ella; no se presume una segunda base por app.
Tareas resuelve `BASE_TAREAS`, que puede ser Django alias o MYSQL_CONFIG. Conservar
referencias externas `_id` sin FKs fisicas cuando estan en bases distintas.

## MembresiaDepartamental (nueva, organizacion/default)

| Campo conceptual | Regla |
|---|---|
| id | PK interna estable |
| empresa, departamento, usuario | FKs protegidas a identidades canónicas locales; Departamento.empresa == Empresa |
| rol | JEFE, SUPERVISOR o STAFF, exactamente uno |
| estado | ACTIVA, SUSPENDIDA o BAJA; estado de membresia, no de tarea |
| version | Revision monotona para detectar preview obsoleto; no reemplaza locks |
| created_at, updated_at | Fechas aware UTC |

Unica `(usuario, empresa, departamento)` aun cuando este suspendida/de baja; una
reactivacion reutiliza esa identidad y crea nuevo evento. No se borra y recrea.
La unicidad de la triple combinacion es mas simple que multiples filas temporales
solapadas; los intervalos historicos se reconstruyen desde eventos.

Como maximo una fila `rol=JEFE AND estado=ACTIVA` por Departamento. En los backends
propietarios que lo soporten, constraint condicional mas validacion de servicio.
Bloquear la fila Departamento para serializar dos altas cuando aun no existe JEFE;
la consulta de una fila inexistente por si sola no evita una carrera. No confiar
en `full_clean()` como barrera concurrente. Certificar restricciones por backend.
La inactividad de Departamento no habilita dos JEFES ACTIVA latentes.

**Efectiva** = membresia ACTIVA + Departamento activo + coherencia Empresa +
usuario activo y acceso Empresa vigente. `estado` no se modifica al perder acceso
SYSTEM o al desactivar un Departamento. No persistir un booleano duplicado de
elegibilidad ni derivar permisos VICMEAS de esta tabla.

Transiciones autorizadas: alta -> ACTIVA; ACTIVA -> SUSPENDIDA/BAJA;
SUSPENDIDA -> ACTIVA/BAJA; BAJA -> ACTIVA mediante recuperacion explicita.
Cambio de rol conserva identidad y genera evento. Toda mutacion exige motivo
no vacio y autor; una solicitud repetida con mismo UUID/payload no duplica historia.

## EventoMembresia (nuevo historial de dominio, organizacion/default)

PK; membresia_id; empresa_id; usuario_afectado_id; departamento_id; autor_id;
fecha; operacion_id UUID; tipo; motivo; rol/estado/version antes y despues.
Relacion local PROTECT, sin borrado ni edicion del evento. UUID + secuencia de evento
identifica de forma unica cada efecto; sustituir JEFE produce dos eventos ligados
al mismo UUID en una transaccion. Una revision autorizada de datos historicos seria
otro evento, no UPDATE del anterior.

Guardar referencias estables, no reconstruir al autor pasado desde el JEFE actual.
Estado/rol anteriores documentan el hecho; cambios futuros del nombre de usuario
no alteran identidad. No copiar datos personales innecesarios.
Este historial prueba vigencia del dominio, no sustituye al servicio de auditoria
transversal. F16-G02 gobierna su proyeccion central.

## ControlOrganizacionEmpresa (coordinacion tecnica propuesta)

Una fila por Empresa, propia de organizacion: empresa_id unico, version y metadata
de coordinacion estrictamente necesaria. Es un fence para mutaciones y consultas
de elegibilidad, no otro sistema de permisos. Se bloquea antes de Departamento/
membresias y se mantiene hasta el commit de tareas cuando proceda.
Creacion inicial serializada; no admitir ausencia del fence como "sin bloqueo".

Una operacion departamental reiniciable puede necesitar registro durable propio
con UUID, departamento_id, actor, motivo, fase tecnica y resultado, sin convertir
`Departamento.activo` en un nuevo lifecycle de negocio. La fase "preparada" no
significa Departamento desactivado; la finalizacion cambia `activo=False` solo
tras comprobar los bloqueos. Ver protocolo en consistencia antes de fijar schema.

## RegularizacionOperacion / RegularizacionDetalle (nuevas, tareas/BASE_TAREAS)

| Entidad | Campos conceptuales e invariantes |
|---|---|
| Operacion | UUID unico; empresa_id; actor_id; origen_id; reemplazante_id; rol; motivo; manifiesto ordenado de IDs; huella del contenido/backend; fecha commit; resultado confirmado |
| Detalle | operacion_id FK interna; tarea_id FK interna; rol; identidad origen/destino; cambio antes/despues; fecha; referencia al ledger de responsable si aplica |

Unico `(operacion_id, tarea_id, rol)`; lote con una Empresa/un rol. IDs de usuario/
Empresa son referencias externas, no FKs remotas. Detalles, cambios y confirmacion
de operacion se guardan en la MISMA transaccion operacional. Fallo antes de commit
no deja detalles de exito. Se puede persistir una reserva tecnica de operacion
antes, pero no confundirla con aplicacion parcial ni notificarla.

No reutilizar el ledger de eliminacion/restauracion para regularizaciones:
sus invariantes y manifiestos tienen otra semantica. Reutilizar patrones de UUID,
fingerprint y replay, no tablas ajenas al dominio.

La sustitucion explicita de un participante puede retirar su vinculo operacional
segun FR-D15, pero primero conserva el hecho anterior en Detalle dentro de la misma
transaccion. La perdida de membresia por si sola nunca ejecuta esa retirada.
No reasignar comentarios, documentos, lecturas ni eventos al reemplazante.

## Compatibilidad y evolucion

- No crear membresias desde tareas historicas, roles VICMEAS, creador o responsable.
- Tareas sin ambito permanecen sin ambito; Opcion B tambien se aplica a ellas.
- No borrar maestros ni historia; admin de nuevas entidades debe ser read-only
  o canalizar mutaciones por el servicio protegido, nunca `save()` directo que
  evada motivo, locks o permisos.
- Migraciones aditivas futuras solo en owner; cobertura administrativa de modelos
  default segun la regla vigente. Nada de DDL ni migraciones en esta entrega.
- Para BASE_TAREAS remoto, extension SQL/versionado/preflight propios y paridad
  con Django; no ejecutar `migrate` implicitamente contra default.
- Constraints no soportados por un motor antiguo no se presumen efectivos.
  F16-G01/G06 exigen alternativa equivalente certificada o bloqueo controlado,
  no degradacion silenciosa.
