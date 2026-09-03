# Estado actual del sistema

## Estado

- Última actualización: 2026-09-03.
- Rama actual: `main`.
- HEAD verificado: `8155a2a`.
- Django 5.1.3 comprobado.
- Python 3.11.4 comprobado en el entorno local utilizado (`..\\venv`). La versión de Python no se declara como requisito universal del proyecto.
- Estado general: sistema Django multiempresa en operación local, con autenticación web, sesiones, permisos ICMEAS, APIs, auditoría, preferencias visuales por usuario y módulos de negocio.
- La información de producción depende de variables de entorno y no se infiere de los defaults locales.

## Arquitectura general

- La aplicación usa Django con una separación entre componentes de sistema y aplicaciones de negocio.
- La empresa activa se conserva en la sesión Django y participa en permisos, navegación y datos multiempresa.
- El acceso normal se controla mediante ICMEAS (`Vista`, `Permiso`, empresa y capacidades como `ingresar`/`modificar`).
- `acounts`, `access_control`, `settings`, `api`, `auditoria` y `database_manager` están clasificados como `CORE_SYSTEM_APPS`.
- `dashboard`, `chat`, `core_search` y `notificaciones` son `SYSTEM_SUPPORT_APPS`.
- `biblioteca`, `gestiondte`, `evaluaciones`, `control_de_proyectos` y `control_operacional` son `APPLICATION_APPS`.
- La clasificación canónica está en `AppDocs/app_classification.py`; no se replica aquí.
- Las `CORE_SYSTEM_APPS` tienen protección reforzada para modificaciones transversales. Ver `COPILOT/ARQUITECTURA_APPS.md`.
- La lógica transversal nueva se concentra, cuando corresponde, en servicios y helpers propios en lugar de alterar vendor.

## Base de datos

- Alias `default`: SQLite local en `BASE_DIR / db.sqlite3`, clasificado `SYSTEM`; es la base usada por el `runserver` local.
- Alias `DB_sistema`: MySQL configurado mediante variables de entorno y clasificado `SYSTEM`. Esta configuración no implica que el alias esté disponible o conectado actualmente. No se documentan nombres de base, usuarios ni credenciales.
- `DATABASE_ROUTERS` usa `api.Router_Databases.MultiDatabaseRouter`.
- Los aliases legacy reconocidos por `common/database_classification.py` se consideran `LEGACY`, aunque no necesariamente estén presentes en `DATABASES`. Los aliases no reconocidos se clasifican `UNKNOWN`.
- La base de datos estándar de sesiones es la de Django, con backend DB y tabla `django_session`.
- Las migraciones de `acounts` incluyen `UserActiveSession`; esa tabla mantiene una única `session_key` activa por usuario. `UserSessionHistory` no existe actualmente en el código.
- No se documenta una estrategia de migración de datos productivos más allá de las reglas y herramientas existentes de `database_manager`; cualquier migración productiva requiere revisión y autorización separada.

## Autenticación y sesiones

- La autenticación web usa `django.contrib.auth.backends.ModelBackend`, `login_required` y sesiones Django mediante cookie.
- `SESSION_COOKIE_HTTPONLY=True` y `SESSION_COOKIE_SAMESITE='Lax'`. `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE` son configurables por entorno.
- `TIME_ZONE='UTC'` y `USE_TZ=True` permanecen vigentes para almacenamiento y cálculos aware.
- La política de sesión es de 8 horas de inactividad: `SESSION_COOKIE_AGE = 8 * 60 * 60` y `SESSION_SAVE_EVERY_REQUEST = True`. Solo actividad humana válida actualiza `last_activity`.
- El flujo de autenticación y selección de empresa registra también en la sesión `login_at`, `last_activity`, IP, User-Agent limitado, `remember_me` y `fecha_sistema`.
- “Recuérdame” marcado fija una expiración de 8 horas. Sin marcar, la cookie es de sesión de navegador, pero el backend mantiene el límite de 8 horas configurado.
- `UserActiveSession` aplica “un usuario = una session_key activa”: el último login invalida la sesión DB anterior. La misma cookie puede usarse en varias pestañas o ventanas.
- La pestaña “Sesiones” muestra solo información de la sesión actual y no expone `session_key`.
- La presentación de datetimes usa `SYSTEM_LOCAL_TIME_ZONE='America/Santiago'` mediante `timezone.localtime`; no cambia los cálculos de seguridad en UTC.
- Ver `COPILOT/LOGIN_RECUERDAME_SESIONES.md` para la política detallada y validaciones documentadas.

## Theme y preferencias visuales

- La fuente de verdad es `settings.models.UserPreferences`, relacionada uno a uno con `User` y no con la empresa activa.
- `settings/context_processors.py` entrega preferencias visuales al template como `theme_preferences`.
- `static/js/theme_config.js` aplica los valores al elemento `<html>`, elimina claves visuales legacy de `localStorage` y mantiene `sessionStorage` como espejo de compatibilidad.
- `static/js/app.js` es vendor inmutable y no debe modificarse.
- `static/js/layout.js` no es la fuente de persistencia visual.
- `ThemePreferences` permanece como modelo legacy; no es la fuente de verdad del theme actual.
- Ver `COPILOT/THEME_PREFERENCES.md` y `COPILOT/REGLAS_CODIGO_VENDOR.md`.

## Apps principales

- `acounts`: autenticación, perfil, avatar, cambio de contraseña, tokens de activación y control de sesión activa.
- `access_control`: empresas, vistas, permisos ICMEAS, perfiles de acceso y solicitudes de acceso.
- `settings`: preferencias de usuario, theme, fecha de sistema y configuración de correo.
- `api`: APIs internas, serializers/viewsets, tokens API y router de bases.
- `auditoria`: eventos y archivado de auditoría.
- `database_manager`: comparación y preflight de bases.
- `dashboard`: dashboard general y navegación base.
- `chat` y `notificaciones`: mensajería y notificaciones.
- `core_search`: búsqueda global.
- `biblioteca`: documentos, propiedades y propietarios.
- `gestiondte`: gestión DTE, cesiones y certificados.
- `control_de_proyectos`: proyectos, tareas, profesionales y documentos.
- `control_operacional`: operación y alertas.
- La clasificación completa pertenece a `AppDocs/app_classification.py`.

## Funcionalidades base implementadas

Comprobadas en código/configuración actual:

- multiempresa con selector y empresa activa en sesión;
- permisos ICMEAS por Vista, usuario, empresa y capacidad;
- perfil de usuario con datos personales, avatar, cambio de contraseña y pestaña de sesión actual;
- autenticación Django con “Recuérdame”, timeout deslizante y exclusividad de una sesión activa por usuario;
- vista inicial por usuario y registro de última vista válida después de cambios de empresa;
- preferencias visuales persistentes por usuario;
- APIs internas con autenticación y tokens API separados de la sesión web;
- comparación/preflight de bases mediante `database_manager`;
- auditoría, búsqueda global, chat y notificaciones;
- gestión de proyectos, tareas, profesionales, dependencias, avance y documentos requeridos/asociados;
- gestión DTE y biblioteca documental.

La existencia de una funcionalidad aquí no implica que todos sus flujos estén libres de pendientes o que exista validación de producción para cada entorno.

## Control de proyectos

El código actual contiene:

- catálogos de tipos de proyecto y especialidades profesionales;
- clientes externos y profesionales vinculables a proyectos;
- proyectos asociados a una empresa interna, cliente, tipo, estado, fechas y presupuesto;
- tareas con estados, prioridades, horas, porcentaje de avance y fechas de planificación/ejecución;
- dependencias entre tareas;
- tipos de tarea y documentos requeridos por tipo;
- documentos asociados a tareas, con estados y referencias a Biblioteca o archivos;
- vistas web protegidas por `VerificarPermisoMixin` y viewsets API.

El modelo `Tarea` contiene fechas y porcentaje para soporte de planificación tipo Gantt. No se afirma aquí una implementación completa de interfaz Gantt sin revisar cada pantalla específica.

## APIs e integraciones

- La configuración principal usa Django REST Framework y tiene `IsAuthenticated` como permiso por defecto en `AppDocs/settings.py`. El entorno `AppDocs/settings_test.py` utiliza un shim/sustituto para tests.
- `api.ApiToken` almacena hash del token, prefijo, expiración, revocación y uso; el valor secreto se entrega al crearlo y no se almacena en claro.
- La autenticación API/token está separada conceptualmente de la autenticación web por sesión Django.
- Existe un router multi-base y modelos legacy/no administrados para integración con estructuras externas.
- `DB_sistema` es el alias MySQL configurado para el sistema; los aliases legacy definidos en `common/database_classification.py` se tratan de forma conservadora.

## Deuda arquitectónica conocida

Según `COPILOT/ARQUITECTURA_APPS.md`:

- `api -> biblioteca`: una app de sistema importa el modelo `Propietario`.
- `control_de_proyectos <-> control_operacional`: existe un ciclo entre aplicaciones de negocio.
- `auditoria` conoce explícitamente Biblioteca y Gestión DTE.

Estas deudas siguen registradas para planificación; este documento no las resuelve ni añade nuevas.

## Pendientes actuales

### Arquitectónicos

- Desacoplar la dependencia `api -> biblioteca` cuando exista un límite de integración adecuado.
- Sustituir gradualmente el ciclo entre `control_de_proyectos` y `control_operacional` por una frontera de integración/eventos.
- Mantener `ThemePreferences` legacy sin convertirlo en fuente de verdad ni eliminarlo sin una tarea específica.

### Funcionales

- `UserSessionHistory` no existe actualmente en el código; por eso no hay un historial visible ni una causa persistida para distinguir expulsión por nuevo login de expiración natural.
- Informar “sesión cerrada por otro login” es una estrategia futura, no una funcionalidad comprometida, y requeriría un registro fuera de la sesión eliminada.

### Infraestructura

- La configuración local mantiene defaults de desarrollo, incluyendo `DEBUG=True` y flags de cookies seguros dependientes del entorno. La configuración productiva de HTTPS, proxy y cookies seguras está documentada/validada en producción según la documentación vigente; no fue inspeccionada directamente en esta sesión.
- El warning de seguridad de `django-ckeditor` 4 aparece en los checks actuales y requiere una decisión futura de migración a una alternativa soportada.
- `static/js/app.js` continúa siendo vendor inmutable.

## Documentación vigente relacionada

| Tema | Documento |
|---|---|
| Arquitectura | `COPILOT/ARQUITECTURA_APPS.md` |
| Vendor | `COPILOT/REGLAS_CODIGO_VENDOR.md` |
| Sesiones | `COPILOT/LOGIN_RECUERDAME_SESIONES.md` |
| Theme | `COPILOT/THEME_PREFERENCES.md` |
| Índice operativo | `COPILOT/INDICE.md` |

## Regla sobre histórico

`COPILOT/historico/` contiene diagnósticos, implementaciones, bugfixes, verificaciones y decisiones anteriores.

Los documentos históricos no representan necesariamente el estado actual.

Ante contradicción, prevalece:

1. código/configuración actual;
2. documentación vigente;
3. `COPILOT/ESTADO_ACTUAL.md`;
4. histórico.

El histórico debe consultarse solo cuando sea necesario investigar cómo se llegó al estado actual o analizar un incidente anterior.

## Regla de mantenimiento

Actualizar este documento únicamente cuando cambie de manera relevante:

- arquitectura;
- seguridad;
- autenticación/sesiones;
- bases de datos;
- infraestructura;
- permisos;
- apps principales;
- persistencia;
- APIs;
- decisiones arquitectónicas;
- funcionalidades base;
- pendientes estratégicos.

No actualizarlo por cambios menores de HTML, CSS, textos o bugfixes locales que no alteren el estado general del sistema.
