# Matriz As-Built: Control de acceso VICMEAS

| Requisito | Implementación | Evidencia test |
|---|---|---|
| V independiente de I | `access_control/services/permissions.py`: `ver` separado de `ICMEAS_FIELDS` | `access_control/tests/test_vicmeas_sidebar.py` |
| superuser respeta V | `get_sidebar_visible_items` filtra por `ver=True` sin rama `is_superuser` | `access_control/tests/test_vicmeas_sidebar.py` |
| sidebar recursivo | `filter_sidebar_tree` y `get_sidebar_access_tree` | `access_control/tests/test_vicmeas_sidebar.py` |
| profundidad arbitraria | Recursión en helpers y `templates/partials/sidebar_node.html` | `access_control/tests/test_vicmeas_sidebar.py` |
| i18n | `label_key` en `permissions.py`, claves en `static/lang/sp.json` y `static/lang/en.json` | `access_control/tests/test_vicmeas_sidebar.py` |
| asignación masiva | `access_control/services/access_utility.py` con operación aditiva y transacción | `access_control/tests/test_access_utility.py` |
| catálogo parcial | Resolución de scopes con `missing_names` y procesamiento de vistas catalogadas | `access_control/tests/test_access_utility.py` |
| ocultar vista | `hide_view_from_sidebar` y acciones del utilitario en `access_control/views.py` | `access_control/tests/test_access_utility.py` |
| bootstrap | `access_control/services/system_bootstrap.py` clasifica vistas SYSTEM/APPLICATION y crea base de acceso | `access_control/tests/test_system_bootstrap.py` |
| dry-run | `inicializar_sistema.py --dry-run` delega a `initialize_system_for_user(dry_run=True)` sin persistir | `access_control/tests/test_system_bootstrap.py` |
| SYSTEM vs APPLICATION | `_classified_route_app`, `SYSTEM_APP_NAMES` y `APPLICATION_APP_NAMES` | `access_control/tests/test_system_bootstrap.py` |
| Topbar SYSTEM obligatorio | `BOOTSTRAP_SYSTEM_VIEW_DEFINITIONS` incorpora `Notificaciones - Topbar` como dependencia del shell/base, preservando `route_name` nulo o legacy | `access_control/tests/test_system_bootstrap.py` |
| Reejecución de usuario existente | `ensure_initial_permissions` completa el permiso faltante de forma aditiva e idempotente | `access_control/tests/test_system_bootstrap.py` |

## Alcance de la evidencia

La matriz describe el estado actual verificado por lectura de código y pruebas existentes.
Documenta la corrección productiva acotada de Topbar y no sustituye la revisión de
seguridad del código CORE.

La evidencia operacional adicional fue: Topbar respondió 403 antes de reejecutar el
bootstrap sobre el mismo usuario y 200 después, de forma repetida. Las demás vistas
ambiguas continúan omitidas.