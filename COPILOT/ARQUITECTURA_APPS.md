# Arquitectura y Apps Protegidas

La fuente tecnica de verdad para la clasificacion de apps es
`AppDocs/app_classification.py`. La documentacion no duplica esas listas.

## Clasificacion

- `SYSTEM_APPS`: infraestructura base compartida.
- `CORE_SYSTEM_APPS`: infraestructura transversal critica dentro de `SYSTEM_APPS`.
- `SYSTEM_SUPPORT_APPS`: infraestructura transversal no critica dentro de `SYSTEM_APPS`.
- `APPLICATION_APPS`: modulos de negocio.

### Dominio organizacional transversal aprobado

Se reserva la futura `APPLICATION_APP` `organizacion` como owner canónico y
reutilizable de los maestros `Local` y `Departamento`. Esta app aún no está
creada, registrada ni autorizada para implementación en esta tarea.

`organizacion` será responsable de `Local`, perteneciente obligatoriamente a
`Empresa`; de `Departamento`, perteneciente obligatoriamente a `Empresa`; y
de futuras dimensiones organizacionales sólo mediante contratos explícitos.
`Departamento` no tendrá una relación obligatoria con `Local`: ambas son
dimensiones alternativas de Empresa.

La futura app no será de seguridad, no reemplazará VICMEAS/ICMEAS y no será el
adaptador ERP. Usará PK internas Django y códigos funcionales únicos por
Empresa. `Local` conservará además un `legacy_code` separado y nullable; ningún
código legacy será PK ni relación de dominio. El ERP legacy será la fuente
externa inicial de Local mediante sincronización futura, mientras Departamento
comenzará como catálogo administrado localmente. Ninguna APPLICATION_APP
consultará SQL legacy directamente ni duplicará estos maestros.

## Lectura y escritura

Copilot puede leer archivos, buscar referencias, auditar, diagnosticar,
revisar Git, ejecutar tests y consultar codigo o configuracion de una
`SYSTEM_APP` sin autorizacion adicional.

Copilot no puede editar, crear, eliminar, mover, renombrar ni refactorizar
archivos dentro de una `SYSTEM_APP` sin autorizacion expresa del usuario en la
tarea actual. Esto incluye models, views, services, decorators, middleware,
urls, forms, serializers, templates, JavaScript, CSS, migrations, management
commands, seeds, tests, admin, signals y utils.

La autorizacion debe identificar la `SYSTEM_APP` y el archivo o alcance
concreto. No autoriza otros archivos, otras apps ni tareas futuras.

## Cambios transversales

Si una tarea cuyo objetivo principal pertenece a una `APPLICATION_APP` requiere
modificar una `SYSTEM_APP`, Copilot debe detener la escritura en la app
protegida e identificar la app, los archivos exactos, el motivo, el impacto
transversal y el riesgo. Solo puede continuar con autorizacion expresa.
La lectura y el diagnostico pueden continuar.

## Proteccion reforzada para CORE_SYSTEM_APPS

Antes de modificar una `CORE_SYSTEM_APP` expresamente autorizada, Copilot debe:

1. Releer `COPILOT/INDICE.md`.
2. Confirmar la autorizacion concreta.
3. Enumerar los archivos CORE autorizados.
4. Explicar el impacto transversal y revisar dependencias relevantes.
5. Aplicar el cambio minimo y ejecutar pruebas especificas y regresiones relacionadas.
6. Ejecutar `git diff --check` y revisar el diff final completo.
7. No hacer commit ni push sin autorizacion expresa.

## APPLICATION BOUNDARY (regla permanente)

Una `APPLICATION_APP` es propietaria únicamente de los archivos dentro de su propio
directorio. Para una tarea cuyo scope sea una APPLICATION, el `WRITABLE ROOT` es
exclusivamente `<application_name>/`. Esto incluye modelos, vistas, formularios, URLs
propias, servicios, templates, static propios, tests, migrations y demás recursos
físicamente contenidos allí.

La APPLICATION puede leer, importar, llamar y consumir modelos, servicios, mixins,
decorators y APIs públicas de otras apps. Consumir una dependencia no transfiere ownership
ni autoriza modificarla. Todo archivo fuera del `WRITABLE ROOT` es READ-ONLY, incluyendo
`AppDocs/`, todas las SYSTEM_APPS, templates/static globales, vendor y otras
APPLICATION_APPS. Una APPLICATION tampoco modifica otra APPLICATION.

### Arquitectura de correo

Las APPLICATION_APPS no implementan SMTP propio si existe un subsistema canónico.
Los eventos automáticos de sistema usan `Empresa` y `purpose` mediante
`acounts.services.email_service.send_email_for_purpose(...)`; la resolución selecciona
la cuenta de `CompanyConfig` y hace fallback a `SystemConfig`, con los purposes vigentes
`security`, `notifications` y `alerts`. El correo automático no usa el SMTP personal del
actor ni interpreta `settings.UserPreferences.email_enabled` como opt-in u opt-out.

Las acciones manuales iniciadas por un usuario que deban usar su correo de perfil usan
`settings.UserPreferences` y `settings.services.email_sender.send_email_message(...)`.
`email_enabled` pertenece únicamente a ese flujo de correo de usuario/perfil. Las
notificaciones in-app son un canal independiente y deben reutilizar
`notificaciones.services.create_notification(...)`.

El alcance efectivo es la intersección entre APPLICATION BOUNDARY y el scope explícito de
la tarea; el scope concreto puede ser más restrictivo y nunca se amplía automáticamente.
Las excepciones históricas de registro inicial no crean una autorización permanente: un
nuevo registro global o cambio de infraestructura requiere una tarea separada, con scope,
archivos autorizados, motivo, tests y regresión explícitos.

### Reutilización de infraestructura base

Una APPLICATION MUST consumir la infraestructura base oficial y NO puede duplicarla,
forkearla, copiarla, parchearla, envolverla para eludir su contrato ni crear SHADOW
INFRASTRUCTURE local. Esto prohíbe equivalentes funcionales locales de VICMEAS/ICMEAS,
empresa activa y multiempresa, autenticación, sesiones, auditoría, notificaciones,
búsqueda global, autenticación API, catálogo de Vistas, materialización de Permisos,
selección de empresa, 403 estructural o preferencias globales.

Los servicios, helpers, selectors y validators propios son válidos únicamente cuando
implementan reglas específicas del dominio de la APPLICATION. El criterio es funcional,
no el nombre del archivo o clase.

### Contrato VICMEAS por APPLICATION_APP

La fuente primaria de autorización de una superficie web es la metadata visible en su
View/FBV activa: `vista_nombre` y `permiso_requerido`, usando el mixin o decorator
oficial. Una superficie funcional conserva una identidad `vista_nombre` estable entre
sus operaciones CRUD; las acciones cambian el permiso requerido, no crean Vistas nuevas.

Un registry declarativo puede aportar metadata secundaria de navegación, catálogo,
utilitario y reporting, pero no puede contradecir la metadata activa ni convertirse en
una segunda autorización divergente. Las definiciones deben validarse contra las rutas
activas y no repetir bindings innecesarios cuando puedan descubrirse genéricamente.

No toda View, URL o función auxiliar es una superficie VICMEAS: autocomplete, AJAX,
lookup, preview, exportación y servicios internos pueden reutilizar la identidad de su
superficie madre.

Esta regla desarrolla los principios VI y VII de `.specify/memory/constitution.md`.

### Dependencias externas y detención

Si el contrato público existente no alcanza y la solución requiere modificar algo fuera
del `WRITABLE ROOT`, no se implementa un workaround local ni se copia la infraestructura.
El caso se clasifica como `BOUNDARY_EXTERNAL_DEPENDENCY` o
`REVIEW_REQUIRED_EXTERNAL_DEPENDENCY` y se informa:

1. APPLICATION afectada;
2. necesidad funcional;
3. app/archivo externo requerido;
4. motivo por el que el contrato público no alcanza;
5. cambio externo mínimo necesario;
6. impacto esperado.

Sólo puede continuar el trabajo independiente que respete el boundary. Modificar una
SYSTEM_APP, CORE_SYSTEM_APP, SYSTEM_SUPPORT_APP u otra APPLICATION exige una tarea
separada y autorización explícita; una necesidad descubierta no constituye autorización.

### Reglas específicas

- `urls.py` dentro de la APPLICATION es modificable; `AppDocs/urls.py` es externo y read-only.
- El sidebar global puede leerse, pero no modificarse desde una APPLICATION. Si vive en
	`access_control/services/permissions.py`, cualquier cambio es una dependencia externa.
- Una APPLICATION puede declarar `vista_nombre` y `permiso_requerido` en sus vistas y usar
	`VerificarPermisoMixin` o los decorators/servicios VICMEAS oficiales, sin modificar
	`access_control` ni crear tablas o bypasses paralelos.
- Las migrations, templates y static modificables son únicamente los que viven dentro de
	la APPLICATION; los recursos globales y vendor son externos.

### Validación física del boundary

Antes de editar se establece `WRITABLE ROOT=<application>/`. Antes de stage se ejecuta:

```text
git status --short --untracked-files=all
git diff --name-only
```

Todo cambio debe pertenecer al `WRITABLE ROOT`; de lo contrario es `SCOPE VIOLATION`:
se detiene, no se stagea, no se borra y no se modifica el archivo externo. Antes del
commit se ejecuta `git diff --cached --name-status`; si existe una ruta externa, el commit
está prohibido. Se usa stage selectivo (`git add -- <application>/<archivo>`), nunca
`git add .` ni `git add -A`.

## Deuda arquitectonica conocida

- `api -> biblioteca`: una app SYSTEM importa el modelo `Propietario`.
- `control_de_proyectos <-> control_operacional`: ciclo entre apps de negocio.
- `auditoria`: conoce explicitamente Biblioteca y Gestion DTE.

Estas deudas se registran para planificacion futura y no autorizan cambios
transversales por si mismas.
