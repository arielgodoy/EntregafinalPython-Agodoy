# Research: Tareas Internas

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md)

Todas las decisiones se resolvieron contra el código y la documentación vigente del
repositorio; no quedan NEEDS CLARIFICATION.

## Decisiones

### D1. Ubicación de la feature: nueva app `tareas` (APPLICATION_APP)

- **Decision**: Crear una nueva app Django `tareas` registrada como APPLICATION_APP.
- **Rationale**: `control_de_proyectos` ya posee un modelo `Tarea` acoplado a proyectos
  (estados operativos, horas, dependencias, documentos, avance). La spec exige un ciclo
  simple borrador/publicada y excluye esos conceptos; mezclar ambos modelos en la misma
  app generaría confusión de conceptos y acoplamiento no solicitado.
- **Alternatives considered**: (a) Dentro de `control_de_proyectos` — rechazada por
  colisión semántica con la `Tarea` de proyectos; (b) Otra APPLICATION_APP existente —
  rechazada porque ninguna (biblioteca, gestiondte, evaluaciones, control_operacional)
  tiene dominio afín.
- **Condición**: registrar la app exige modificar `AppDocs/app_classification.py`,
  `AppDocs/settings.py` (INSTALLED_APPS) y `AppDocs/urls.py` (include), todos archivos
  CORE/SYSTEM. La elección de app nueva NO constituye autorización para tocarlos: esos
  cambios quedan **PENDIENTES DE AUTORIZACIÓN EXPRESA DEL USUARIO ANTES DE IMPLEMENTAR**.
  Hasta obtenerla, la implementación del registro está bloqueada.

### D2. Control de acceso: `VerificarPermisoMixin` + `LoginRequiredMixin` (CBV)

- **Decision**: Todas las vistas usan `VerificarPermisoMixin` (con `vista_nombre` y
  `permiso_requerido`) delante de `LoginRequiredMixin`, siguiendo el patrón exacto de
  `control_de_proyectos/views.py`.
- **Rationale**: Es el mecanismo ICMEAS vigente (constitución, principio V). El mixin
  delega en el decorador `verificar_permiso`, que resuelve empresa desde la sesión,
  crea la `Vista` si no existe, aplica deny-by-default y responde con
  `access_control/403_forbidden.html` permitiendo solicitar acceso.
- **Alternatives considered**: decorador de función `@verificar_permiso` — equivalente,
  pero las CBV son el patrón dominante en las APPLICATION_APPS recientes.

### D3. Aislamiento multiempresa

- **Decision**: Campo `empresa = FK(access_control.Empresa)` en el modelo; los querysets
  filtran por `request.session['empresa_id']` (helper local `_get_empresa_id` igual que
  en `control_de_proyectos`); al crear, la empresa se asigna desde la sesión, nunca desde
  parámetros del request.
- **Rationale**: Principio II/V de la constitución y regla vigente: nunca confiar en
  parámetros para selección de empresa; validar pertenencia en detalle/edición/eliminación.
- **Alternatives considered**: queryset global + validación posterior — rechazada:
  expone existencia de objetos de otras empresas.

### D4. Ciclo de vida borrador → publicada

- **Decision**: Campo `estado` con choices `BORRADA`/`PUBLICADA` (valores string) y
  `fecha_publicacion` nullable. `publicar()` es un método del modelo que valida
  responsable válido (asignado, activo) antes de transicionar y fijar
  `fecha_publicacion = timezone.now()`. La publicación es irreversible: no existe
  operación de retorno a borrador.
- **Rationale**: FR-005…FR-009 + Clarifications (Q1: bloquear publicación con responsable
  inválido; Q2: edición libre post-publicación sin retorno a borrador).
- **Alternatives considered**: flag booleano `publicada` — rechazada porque el enum deja
  espacio documentado a estados futuros sin migración conceptual, y la spec habla de
  "estado" como atributo propio.

### D5. Prioridad

- **Decision**: Valores aprobados por el usuario: `simple`, `normal`, `urgente`,
  `crítica`, con jerarquía `crítica > urgente > normal > simple`. **Default: `NORMAL`**
  (aprobado por el usuario).
- **Rationale**: Definición oficial entregada por el usuario. NO se inventan
  comportamientos adicionales por prioridad: sin colores, SLA, notificaciones,
  vencimientos ni reglas especiales en esta versión.
- **Alternatives considered**: niveles baja/media/alta — rechazados explícitamente por el
  usuario.

### D6. Eliminación: FUERA DE ALCANCE en esta versión

- **Decision**: Esta primera spec NO incluye eliminación de tareas. No se define ruta,
  vista, modal, JS ni permiso `eliminar` para la app `tareas`.
- **Rationale**: El alcance aprobado por el usuario se limita a crear/editar/publicar y
  listar. Si en el futuro se solicita eliminación, se evaluará entonces conforme a las
  reglas vigentes del proyecto; esta feature no presupone ningún patrón de eliminación.
- **Alternatives considered**: incluir eliminación desde el inicio — rechazada por no
  estar en el alcance aprobado.

### D7. Internacionalización

- **Decision**: Todo texto visible con `data-key`; las claves nuevas se reportan al usuario
  para su alta en `static/lang/sp.json` y `static/lang/en.json` (no se editan silenciosamente).
- **Rationale**: Regla i18n vigente (AGENTS.md / copilot-instructions.md).

### D8. Visibilidad en menú

- **Decision**: El mecanismo exacto de registro de la vista "Tareas" en menú e ICMEAS
  queda como tarea de LECTURA/VERIFICACIÓN durante la implementación (T026). NO se asume
  visibilidad sin permiso ni auto-creación de `Vista`. Si se requiere crear `Vista`,
  modificar menú, seed, `access_control` u otra SYSTEM_APP, se detiene y se solicita
  autorización expresa indicando archivos exactos.
- **Rationale**: `copilot-instructions.md` establece preferencias de visibilidad/autorización,
  pero el mecanismo concreto debe verificarse en el código vigente antes de actuar.

### D9. Fechas

- **Decision**: `fecha_creacion = auto_now_add` (UTC); `fecha_publicacion` seteada con
  `timezone.now()` al publicar. Presentación con `timezone.localtime` (tz local del sistema).
- **Rationale**: Coherente con `ESTADO_ACTUAL.md` (USE_TZ, UTC, presentación
  America/Santiago vía localtime).

### D10. Router de bases de datos

- **Decision**: La app no define router ni `app_label` especial; sus tablas van al alias
  `default` según `api.Router_Databases.MultiDatabaseRouter`.
- **Rationale**: `common/utils.py` y `api/Router_Databases.py` son archivos protegidos; el
  comportamiento por defecto ya enruta apps de negocio al alias estándar.
