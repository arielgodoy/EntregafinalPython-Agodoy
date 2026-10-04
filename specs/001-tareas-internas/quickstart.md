# Quickstart: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Guía de validación ejecutable y progresiva. Los detalles de campos y rutas están en
[data-model.md](data-model.md) y [contracts/web-urls.md](contracts/web-urls.md); aquí solo
se describen escenarios de verificación end-to-end.

> **REGISTRO INICIAL RESUELTO**: el alta de la app en `AppDocs/app_classification.py`,
> `INSTALLED_APPS` y `AppDocs/urls.py` ya fue autorizada, ejecutada, testeada y versionada.
> Cualquier modificación futura adicional de esos archivos requiere una tarea separada con
> autorización y scope explícitos; no es una excepción al APPLICATION BOUNDARY.

## Prerequisitos

### Conexiones SQL de Tareas (validacion futura)

1. Sin `ingresar`, GET devuelve 403.
2. Con `ingresar`, la superficie muestra exactamente los cuatro roles globales.
3. Con `modificar`, un POST valido devuelve 302.
4. `BASE_TAREAS` acepta Django y MySQL.
5. `AUDITORIA_TAREAS` acepta Django y MySQL.
6. `LEGACY_MYSQL` rechaza Django.
7. `LEGACY_AUDITORIA` rechaza Django.
8. Un role inexistente, alias invalido, conexion inexistente/inactiva o `database_name`
   invalido devuelve error controlado.
9. No existe fallback a `default`.
10. Con Empresa 09 activa, el catálogo MySQL de Tareas sigue mostrando únicamente
   conexiones activas asociadas a Empresa código `00`; la empresa activa no interviene.
11. Los tests confirman ausencia de imports desde `gestiondte` y ausencia de credenciales
   en HTML, respuestas y logs.

Estos escenarios son futuros y no implican implementacion en esta actualizacion documental.

1. Entorno local del proyecto activo (venv, dependencias ya instaladas según README).
2. Migraciones de la fase habilitada aplicadas:
   ```powershell
   python manage.py migrate
   ```
3. El sidebar consume la infraestructura VICMEAS existente: `Permiso.ver` controla solo
   visibilidad por empresa activa y el mapping explícito de items a Vistas. No se agrega
   una implementación de VICMEAS en `tareas`; cualquier cambio futuro en SYSTEM_APPS
   requiere una tarea separada con autorización y scope explícitos.
4. Un usuario con empresa activa en sesión y permisos ICMEAS sobre las vistas `Tareas - *`
   para las acciones que probará, y `Permiso.ver` cuando deba verificar visibilidad.

## Validación automatizada por fase

```powershell
python manage.py test tareas --settings=AppDocs.settings_test
python manage.py check
```

Resultado esperado: todos los tests de `tareas/tests/` pasan; `check` sin errores nuevos.

### Estado de reconciliación de validación

- `AUTOMATED_VALIDATED`: suite `tareas` y gates focalizados ejecutados con resultado verde.
- `AUTOMATED_I18N_GATE=PASS`: `tareas.tests.test_i18n` ejecutado; las claves usadas por
   código y templates de `tareas` están presentes y son simétricas en ambos catálogos.
- `MANUAL_VALIDATION_PENDING`: permanece para los escenarios fuera de E14 que conservan
   ese estado; E14 se cierra como PASS con la evidencia aceptada que se registra abajo.
- `MANUAL_ES_EN_REVIEW=PENDING`: permanece para las superficies fuera de E14 que sigan
   pendientes. La revisión manual ES/EN de Comentarios E14 está en PASS.

## Escenarios manuales end-to-end

Levantar el servidor local (task "Django: Runserver (local)") y verificar:

### E1. Crear borrador mínimo (FR-001, FR-003, FR-005)

1. Login → empresa activa seleccionada.
2. Menú → "Tareas" → Crear. Ingresar solo título → Guardar.
3. **Esperado**: tarea visible en el listado con estado "Borrador", fecha de creación de hoy,
   empresa = empresa activa.

### E2. Borrador indefinido y edición (FR-006, FR-009)

1. Editar el borrador: cambiar descripción/prioridad/responsable → Guardar.
2. **Esperado**: sigue en "Borrador", sin fecha de publicación; sin límite de tiempo.

### E2 bis. Administrar responsable desde el detalle (FR-D11)

1. Abrir el detalle de un borrador y seleccionar un usuario activo válido como responsable.
2. Guardar la administración del responsable desde el bloque de participantes.
3. **Esperado**: el responsable queda visible en el detalle sin crear una fila
   `TareaParticipante`; quitarlo vuelve a ser posible mientras la tarea siga en borrador.
4. Publicar la tarea y comprobar que el selector ya no permite dejar el responsable vacío;
   una reasignación válida conserva el registro de reasignación.

### E3. Publicación bloqueada sin responsable (FR-007)

1. Quitar el responsable del borrador → intentar Publicar.
2. **Esperado**: rechazo con mensaje claro; la tarea permanece en "Borrador".

### E4. Publicación exitosa (FR-008)

1. Asignar un responsable activo → Publicar.
2. **Esperado**: estado "Publicada", fecha de publicación registrada y visible en el detalle.

### E5. Publicación irreversible + responsable obligatorio (Q2, FR-008)

1. En la tarea publicada: verificar que NO existe acción "volver a borrador".
2. Intentar editar dejando el responsable vacío.
3. **Esperado**: error de validación; la tarea conserva responsable y fecha de publicación.

### E6. Aislamiento multiempresa (FR-003, FR-010)

1. Cambiar la empresa activa a otra empresa del usuario.
2. **Esperado**: el listado no muestra las tareas de la empresa anterior; el acceso directo
   por URL a una tarea de otra empresa responde 404.

### E7. VICMEAS e ICMEAS independientes (FR-011)

1. Con `Permiso.ver=True` y `Permiso.ingresar=True` en `Tareas - Listado`: el item aparece
   y el acceso funciona.
2. Con `Permiso.ver=True` y `Permiso.ingresar=False`: el item sigue visible, pero el
   backend responde **403** con la página que permite solicitar acceso.
3. Con `Permiso.ver=False` y `Permiso.ingresar=True`: el item no aparece, pero el acceso
   directo por URL funciona.
4. Con ambas banderas en `False`: el item no aparece y el acceso está prohibido.
5. Repetir la comprobación en dos empresas: `ver` en una empresa no hace visible el item
   en la otra. El superuser ve el sidebar completo por bypass visual, sin inferir bypass
   backend. Los padres aparecen solo si un hijo es visible.

## Validaciones del dominio por fases

### E8. Correlativos y estados (Phase 2)

- Crear un borrador y comprobar correlativo `B*` único por empresa.
- Publicar con responsable válido y comprobar conversión al correlativo `A*` sin nueva PK.
- Ejecutar transiciones permitidas y rechazar saltos de estado; verificar auditoría.
- Al marcar 100%, comprobar `cierre_completado == True` y estado `PENDIENTE_APROBACION_CIERRE`.
- Aprobar cierre y comprobar estado `CERRADA` con `cierre_completado == True`.
- Rechazar cierre y comprobar retorno a `GESTION` conservando `cierre_completado == True`;
   esta señal es lifecycle, no porcentaje general de avance.

### E9. Asignación y jerarquía (Phase 3)

- Crear padre, hijos y nietos dentro del máximo permitido (padre→hija→nieta, sin cuarto nivel).
- Anular el padre y comprobar que SOLO cambia `padre.anulada=True`; hijas/nietas conservan
  `anulada=False` y sus estados funcionales intactos, pero todas quedan anuladas
  efectivamente (lógica: tarea+padre+abuelo). Verificar notificación a participantes.
- Reactivar el padre y comprobar que SOLO cambia `padre.anulada=False`; los estados
  funcionales de toda la estructura siguen intactos (nunca cambiaron; no hay restauración).
- Confirmar que una hija anulada directamente (`anulada=True`) sigue anulada tras
  reactivar el padre.
- Confirmar que fechas afectadas quedan pendientes, sin recálculo automático.
- Bloqueo documentado: la notificación a participantes no está conectada desde
   `tareas`; queda pendiente de integración y no se implementa P1 Local en esta fase.

### E10. Hitos, mini-tareas y documentos (Phase 3)

- Validar `sum(cumplimiento * peso) / sum(pesos)` y redistribución al agregar un hito.
- Comprobar que mini-tareas pendientes bloquean cierre y no ponderan avance.
- Adjuntar documento/evidencia, cambiarlo y verificar historial y vencimiento informativo.

### E11. Cotizaciones (Phase 4)

- Crear o reutilizar proveedores del maestro local Django y abrir una `RondaCotizacion`.
- Crear cotizaciones asociadas a proveedores locales, conservando cotizaciones históricas con `proveedor=NULL` sin contarlas para el mínimo.
- Verificar máximo de 3 versiones por `(ronda, proveedor)`, mínimo por proveedores distintos y que varias versiones del mismo proveedor cuentan una sola vez.
- Confirmar que el cierre de ronda se bloquea hasta cumplir el mínimo y que cotizaciones vigentes de proveedores distintos permiten cerrarla.
- Marcar una cotización como `SELECCIONADA`, comprobar que el proveedor seleccionado es visible dentro de Django y que no se crea `Adjudicacion`.
- Reutilizar el cierre de Tarea vigente y validar que la ronda más reciente controla el mínimo.
- Confirmar que todo el flujo opera con el maestro local Django sin consultar ERP/legacy; la integración, conciliación y sincronización permanecen bloqueadas por P2.

Estado E11 PRE-P2: EJECUTADO/VALIDADO exclusivamente sobre las capacidades
internas autorizadas: rondas, mínimos, estados, fechas, observaciones,
documentos, histórico, selección interna, cierre controlado, nuevas rondas,
maestro local Django y versionado por `(ronda, proveedor)`.

Estado P2 ERP/legacy: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN. Quedan
fuera de esta validación la identidad externa del proveedor, lookup ERP,
validación ERP, conciliación, sincronización y actualización desde legacy.
No se declara identidad ERP ni se implementa integración legacy.

### E12. Colaboración, similitud y enlaces (Phase 5)

- Verificar notificaciones internas/email mediante mocks y reuniones de revisión.
- Comparar con tareas abiertas y cerradas usando 80% por defecto; cambiar umbral por empresa
   y comprobar que solo afecta evaluaciones nuevas.
- Abrir enlace como usuario autenticado de la empresa y rechazar acceso cross-company/externo.

Estado E12: EJECUTADO/VALIDADO mediante la regresión focal de colaboración,
similitud, enlaces y reuniones, con mocks de notificaciones/email y cobertura
de aislamiento cross-company.

### E13. Dashboards (Phase 6)

- Comprobar exactamente ocho KPI en cada dimensión permitida: estado, atrasadas, próximas a
   vencer, sin movimiento, aprobación pendiente, carga, cumplimiento y tiempo promedio de cierre.
- Verificar drill-down, paginación y aislamiento; mantener Local/Proveedor bloqueados sin legacy.

Estado E13: EJECUTADO/VALIDADO mediante la regresión integrada de KPI,
dashboards, T060, dashboard personal y metadata, manteniendo Local/Proveedor
fuera de las dimensiones de drill-down.

### E14. Comentarios de Tarea (Phase 8 completada; T102 y validación manual PASS)

Phase 8 está implementada. T102 se cerró el 2026-10-01 tras completar la regresión
automatizada y los gates, y aceptar la evidencia manual del Product Owner registrada al
final de esta sección. Criterios de aceptación cubiertos:

- La tarjeta aparece en el detalle para usuarios autorizados a leer el feed. La participación
   funcional efectiva (creador, responsable, participante explícito o responsable de Hito
   vigente) habilita cursor y reconocimiento según el contrato. Un lector sin vínculo
   funcional puede consultar el feed con `ingresar`, Empresa activa y acceso válido a la
   Tarea, pero no obtiene composer, cursor, unread, badge ni reconocimiento. Desvincular
   elimina la participación explícita salvo que conserve otro vínculo funcional; VICMEAS
   no crea permisos especiales.
- Solo estados publicados operativos (`ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`)
   admiten mutaciones. `CERRADA`, `BORRADOR` y anulada son lectura; reactivar un estado
   operativo permite comentar otra vez y conserva cursor/versiones.
- Crear exige VICMEAS `crear` y participación funcional; editar exige `modificar`, ser
   autor y participación funcional; ocultar/restaurar exige S (`supervisor`), participación
   funcional y motivo no vacío. El historial de comentarios visibles lo ve el autor; el
   historial y contenido de comentarios ocultos solo los ve S. El autor no-S recibe tombstone.
- Texto y/o adjuntos son válidos; el sexto adjunto se rechaza. Reutilizar `DocumentoTarea`
   de la misma Tarea, permitir captura móvil y comprobar que quitar el vínculo no elimina
   el documento ni convierte el adjunto en evidencia formal.
- La bitácora es lineal, sin filtros, buscador, threads ni aplicación/chat separados; la
   carga inicial y cada página son de 20. Abrir la Tarea no marca Comentarios leídos.
- Al expandir/cargar, solo los próximos 20 Comentarios cronológicos contiguos avanzan el
   cursor; navegar a una página histórica/arbitraria no lo mueve ni salta pendientes. Sin
   pendientes, el card muestra los 20 más recientes. El contador muestra `1..9`/`9+`, enfoca
   el primer pendiente, considera leídos los Comentarios propios, conserva ocultos pendientes
   hasta cargar su tombstone y no incrementa por edición/ocultar/restaurar.
- El cursor se guarda en la fila única `TareaLectura` usuario/Tarea; el alta tardía inicia
   en el Comentario más reciente, sin pendientes históricos, y los Comentarios de intervalos
   `is_active=False` no se acumulan. No se crean filas de lectura por Comentario ni recibos
   individuales.
- Crear/editar/ocultar/restaurar notifica a participantes activos vinculados, excluye al
   actor y deduplica; solo crear incrementa no leídos. `CRITICA` conserva email automático;
   no se duplica `documento_agregado` por adjunto inline.
- Comentarios no reemplaza motivos/justificaciones formales; cada escritura revalida en
   backend Empresa, vínculo, VICMEAS y estado justo antes de guardar.
- La autorización contextual administrativa de `tareas` se validó por separado: creador con
   `modificar` y `supervisor` pueden editar datos generales y administrar responsable o
   participantes/invitados; un actor `M-only` no creador, aunque sea responsable o participante,
   recibe 403 y no muta la Tarea. Un creador sin `modificar` también recibe 403. Esta regla no
   concede ni revoca la capacidad independiente de comentar.
- La UI y los mensajes de Comentarios se revisaron en ES/EN y el gate i18n está PASS; el
   detalle de la evidencia manual final se registra abajo.

Estado E14: PASS / COMPLETADO.
Estado T102: [x] CLOSED.
Estado de validación Phase 8: CLOSED.

Regresión final del 2026-10-01: 542 tests de `tareas` PASS; `manage.py check` sin errores
(warning conocido `ckeditor.W001`); `compileall tareas` PASS; JSON de `sp.json` y `en.json`
válido; gate automatizado `tareas.tests.test_i18n` PASS. El workaround de migraciones para
`gestiondte` se aplicó solo en runtime y no se persistió. No hubo cambio de schema ni
migraciones nuevas.

Evidencia manual aceptada del Product Owner (A–N): A creador implícito; B `fecha_tope`;
C responsable y reasignación; D invitado/observador y revinculación; E polling; F unread y
cursor; G paginación; H inactividad; I notificaciones y deduplicación; J adjuntos y máximo
cinco; K captura real con cámara en iPhone; L lifecycle; M edición e historial; N
ocultar/restaurar con S y separación entre autor y S.

Validación manual final E14 del Product Owner: cambio ES → EN → ES correcto; las etiquetas
generales del módulo de Comentarios y la etiqueta dinámica del tipo de adjunto se traducen
en ambos sentidos; no se detectaron problemas funcionales. `MANUAL_ES_EN_REVIEW` para E14
es PASS. La evidencia física de cámara FR-T04 se conserva como PASS reportado por el
Product Owner y no se repitió durante este cierre.

## Límites y bloqueos

- No hay eliminación física; se usa anulación auditada.
- P1 Local: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN; permanece `LEGACY API PENDIENTE`.
- P2 Proveedor: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN para integración,
  validación y conciliación con ERP legacy; el maestro Django local no queda bloqueado.
- No hay usuarios externos, plantilla de hitos ni vencimiento automático de documentos.
- El alta inicial ya está resuelta; cualquier modificación futura de `AppDocs/*` requiere
   autorización expresa.

## Verificación de cierre

```powershell
git diff --check
git status --short
```

### Gate permanente de i18n

Antes de cerrar cualquier cambio de UI en `tareas`, ejecutar el inventario y la
validación funcional en ambos idiomas. Una superficie solo está completa cuando
el `data-key` o `message_key` es correcto, existe en `static/lang/sp.json` y
`static/lang/en.json`, no es dinámico, los enums visibles tienen etiqueta i18n,
los mensajes backend/AJAX se resuelven y la pantalla fue comprobada en ES y EN.

El cierre requiere:

```powershell
python manage.py test tareas.tests.test_i18n --settings=AppDocs.settings_test
```

Y estas métricas en cero: `MISSING_SP`, `MISSING_EN`, `ONE_SIDE`, `DYNAMIC_KEYS`,
`RAW_MESSAGE_KEYS_VISIBLE` y `VISIBLE_HARDCODED_TEXT`, salvo excepciones
explícitamente justificadas y registradas. El inventario debe cubrir templates,
formularios, vistas, JavaScript app-local y ambos catálogos.

La comprobación manual mínima recorre sidebar, listado, crear/editar, detalle,
ciclo de vida, mis hitos y tareas, hitos, documentos/evidencias, cotizaciones,
reuniones, similitud, enlaces, dashboards y TO-DO si su UI está activa; debe
alternar ES → EN → ES sin reiniciar datos ni alterar la lógica.

Esperado: diff sin errores de whitespace; cambios de código limitados a `tareas/` y `specs/`.
Los cambios futuros adicionales en `AppDocs/app_classification.py`, `AppDocs/settings.py` y
`AppDocs/urls.py` sólo pueden aparecer en una tarea separada con autorización y scope
explícitos; desde este scope son dependencias externas.
Sin commit ni push sin autorización expresa del usuario.
