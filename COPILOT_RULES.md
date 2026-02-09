# COPILOT_RULES.md

## 0) Principio base
- Antes de cualquier cambio: leer este archivo COMPLETO y respetarlo.
- Prioridad máxima: NO romper nada que ya esté operativo en producción.
- Preferir cambios pequeños, verificables y reversibles (commits chicos).

## 1) Contexto del sistema
- Proyecto Django multi-rubro, multi-empresa, multi-rol y multi-cliente.
- “Empresa activa” se define por sesión (empresa_id / empresa_codigo / empresa_nombre) y se usa para scoping en views/queries.
- Permisos se controlan por: usuario + empresa + vista + flags (ingresar/crear/modificar/eliminar/autorizar/supervisor).

## 2) Reglas de seguridad y compatibilidad (NO negociables)
- No duplicar Bootstrap (bootstrap.bundle.js) ni DataTables assets. Cargar 1 sola vez.
- No introducir librerías nuevas si ya existe un patrón interno (ej: DataTables en biblioteca).
- No cambiar constraints/UniqueConstraint existentes sin plan de migración y sin validación de impacto.
- Mantener compatibilidad con SQLite y el entorno local.
- Evitar N+1 queries: usar select_related/prefetch_related/annotate cuando corresponda.

## 3) Multiempresa / Scoping (regla crítica)
- Toda vista/listado/modificación que afecte entidades “scoped” debe filtrar por empresa activa:
  - Proyecto.empresa_interna = empresa activa
  - Permiso.empresa = empresa activa
  - ThemePreferences.empresa = empresa activa
- Si una vista olvida filtrar por empresa, se considera BUG crítico.
- Profesionales y Clientes pueden ser globales (no scopiados) según definición de negocio.

## 4) UI dinámica: IDs únicos + Bootstrap Collapse (regla crítica)
- Todo elemento con data-bs-toggle="collapse" debe tener:
  - data-bs-target válido (NO "#", NO vacío)
  - aria-controls válido
  - el panel collapse debe tener id válido y único
- En componentes repetidos (listas/child rows/partials), los IDs deben incluir prefijos únicos:
  - proyecto_id + tarea_id + sufijo (ej: proyecto-<pid>-tarea-<tid>-docs-entrada)
- No renderizar HTML con IDs duplicados en “containers ocultos” dentro del DOM.
  - Si se necesita pre-render para DataTables child row, usar <template> y clonar content.

## 5) DataTables + Child Rows
- No meter UI interactiva pesada en el <tr> principal (sliders, acordeones internos, formularios).
- El detalle (acordeón + sliders + documentos) va en el child row.
- JS debe funcionar después de redraw: usar delegación de eventos o hooks de DataTables (drawCallback).
- Si se inserta HTML dinámico: re-inicializar handlers con una función tipo initX(rootElement).

## 6) Estándares de desarrollo
- Mantener estructura existente del proyecto (apps, partials, templates).
- Reutilizar patrones de biblioteca cuando corresponda (DataTables, estilo, i18n si aplica).
- No “refactor masivo”. Si se necesita, dividir en PR/commits.

## 7) Logging y debugging
- Cuando haya errores de UI:
  - reproducir
  - revisar consola/network
  - identificar causa raíz exacta
  - aplicar fix mínimo
- Si aparece “'#' is not a valid selector”, buscar y eliminar data-bs-target="#" / href="#" / data-bs-parent inválidos.

## 8) NUEVAS REGLAS: Tests en carpeta tests/ (OBLIGATORIO)
- Todos los tests deben vivir dentro de una carpeta `tests/` por app (paquete Python).
- No usar tests sueltos en `tests.py` en raíz de la app (migrarlos).
- Estructura estándar por app:
  - <app>/
    - tests/
      - __init__.py
      - test_models.py
      - test_views.py
      - test_forms.py
      - test_api.py (si aplica)
      - test_permissions.py (si aplica)
- Naming obligatorio:
  - Archivos: test_*.py
  - Clases: Test*
  - Métodos: test_*
- Descubrimiento de Django:
  - Asegurar que exista `tests/__init__.py` para que Django detecte el paquete.
- Cobertura mínima por módulo nuevo:
  - 1 test de modelo (creación/str/constraint)
  - 1 test de permisos/empresa activa (scoping)
  - 1 test de vista o endpoint (GET/POST básico)
- Prohibido escribir tests que dependan de datos reales de producción.
- Usar factories/fixtures mínimas (crear Empresa/Usuario/Permiso/Proyecto según corresponda).
- Cada cambio funcional debe incluir o actualizar tests relevantes.

## 9) Checklist antes de entregar cambios
- Migraciones: makemigrations + migrate sin errores.
- Lint básico: no errores obvios en consola.
- Tests: ejecutar `python manage.py test` sin fallos.
- Multiempresa: validar que listados/creación/edición respetan empresa activa.
- UI: acordeones/collapses funcionan (abrir/cerrar) y no hay IDs duplicados.

