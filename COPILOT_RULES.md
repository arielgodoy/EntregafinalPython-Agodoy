# COPILOT_RULES.md

## 0) Principio base
- Antes de cualquier cambio: leer este archivo COMPLETO y respetarlo.
- Prioridad máxima: NO romper nada que ya esté operativo en producción.
- Para operaciones de ELIMINACIÓN en toda la app: ver archivo `AJAX_DELETION_PATTERN.md` (patrón obligatorio).
- Este archivo DEBE existir físicamente en el repositorio.
- El patrón descrito allí debe coincidir EXACTAMENTE con la implementación actual del sistema.
- Prohibido crear variantes del patrón sin actualizar también `AJAX_DELETION_PATTERN.md`.

## 1) Contexto del sistema
- Proyecto Django multi-rubro, multi-empresa, multi-rol y multi-cliente.
- "Empresa activa" se define por sesión (empresa_id / empresa_codigo / empresa_nombre) y se usa para scoping en views/queries.
- Permisos se controlan por: usuario + empresa + vista + flags (ingresar/crear/modificar/eliminar/autorizar/supervisor).

## 2) Reglas de seguridad y compatibilidad (NO negociables)
- No duplicar Bootstrap (bootstrap.bundle.js) ni DataTables assets. Cargar 1 sola vez.
- No introducir librerías nuevas si ya existe un patrón interno (ej: DataTables en biblioteca).
- No cambiar constraints/UniqueConstraint existentes sin plan de migración y sin validación de impacto.
- Mantener compatibilidad con SQLite y el entorno local.
- Evitar N+1 queries: usar select_related/prefetch_related/annotate cuando corresponda.

## 3) Multiempresa / Scoping (regla crítica)
- Toda vista/listado/modificación que afecte entidades "scoped" debe filtrar por empresa activa:
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
- No renderizar HTML con IDs duplicados en "containers ocultos" dentro del DOM.
  - Si se necesita pre-render para DataTables child row, usar <template> y clonar content.

## 5) DataTables + Child Rows
- No meter UI interactiva pesada en el <tr> principal (sliders, acordeones internos, formularios).
- El detalle (acordeón + sliders + documentos) va en el child row.
- JS debe funcionar después de redraw: usar delegación de eventos o hooks de DataTables (drawCallback).
- Si se inserta HTML dinámico: re-inicializar handlers con una función tipo initX(rootElement).

## 6) Estándares de desarrollo
- Mantener estructura existente del proyecto (apps, partials, templates).
- Reutilizar patrones de biblioteca cuando corresponda (DataTables, estilo, i18n si aplica).
- No "refactor masivo". Si se necesita, dividir en PR/commits.

## 7) Logging y debugging
- Cuando haya errores de UI:
  - reproducir
  - revisar consola/network
  - identificar causa raíz exacta
  - aplicar fix mínimo
- Si aparece "'#' is not a valid selector", buscar y eliminar data-bs-target="#" / href="#" / data-bs-parent inválidos.

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
  - Asegurar que exista tests/__init__.py para que Django detecte el paquete.
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
- Tests: ejecutar python manage.py test sin fallos.
- Multiempresa: validar que listados/creación/edición respetan empresa activa.
- UI: acordeones/collapses funcionan (abrir/cerrar) y no hay IDs duplicados.

REGLA OBLIGATORIA – SISTEMA MULTILENGUAJE (i18n)

Este proyecto es MULTILENGUAJE (ES / EN).

REGLAS ESTRICTAS:

1. TODO TEXTO VISIBLE AL USUARIO DEBE TENER EL ATRIBUTO:
   data-key="clave.traduccion"

   Esto incluye, SIN EXCEPCIÓN:
   - Títulos (h1–h6)
   - Labels
   - Botones
   - Links
   - Placeholders
   - Mensajes de error / éxito
   - Textos dentro de modales
   - Textos de tablas
   - Textos condicionales renderizados por lógica
   - Menús y submenús
   - Tooltips y ayudas visuales
   - Placeholders de <input>, <textarea> y <select>

2. NO se deben dejar textos hardcodeados visibles al usuario sin data-key.

3. Las claves de traducción deben:
   - Usar lowercase
   - Usar puntos como separador
   - Ser descriptivas y estables
   Ejemplo:
     data-key="users.invite.title"
     data-key="buttons.send_invitation"

4. El sistema utiliza los archivos:
   /static/lang/en.json
   /static/lang/sp.json

   Toda nueva clave agregada en templates DEBE:
   - Ser incluida en AMBOS archivos JSON
   - Mantener equivalencia semántica entre idiomas

5. Si se modifica un template existente:
   - Se deben agregar data-key a TODOS los textos visibles nuevos o existentes
   - No se permite mezclar textos con y sin data-key

6. No romper funcionalidad existente:
   - Solo se agrega data-key
   - No se cambia lógica ni comportamiento salvo que se solicite explícitamente

7. Si falta una traducción:
   - Se debe crear la clave
   - Se deben agregar los valores en en.json y sp.json
   - No se deja texto sin traducir como "temporal"

8. i18n EN JAVASCRIPT (OBLIGATORIO):
   - Todos los textos generados dinámicamente desde JS (toasts, alerts, innerHTML, confirmaciones, mensajes de error) deben usar el sistema de traducción.
   - Está PROHIBIDO hardcodear strings visibles en JS.
   - Se debe utilizar la función global de traducción ya existente en el proyecto.
   - Está PROHIBIDO crear nuevas funciones de traducción si ya existe una implementación global.

ESTA REGLA ES OBLIGATORIA PARA TODO HTML, TEMPLATE, MODAL O COMPONENTE UI.

FORMATO DE RESPUESTA
- TODA respuesta DEBE entregarse en UN SOLO BLOQUE DE TEXTO completamente copiable.
- PROHIBIDO dividir la salida en múltiples bloques.
- PROHIBIDO agregar explicaciones fuera del bloque.
- ENTREGAR SIEMPRE RESPUESTAS EN TEXTO PLANO.
- NO usar Markdown fuera de bloques de código.
- NO usar múltiples bloques separados.

COMPORTAMIENTO
- NO pedir confirmaciones intermedias.
- NO dejar pasos "para después".
- NO detenerse por supuestos faltantes; documentarlos dentro del bloque y continuar.
- NO modificar login/logout ni UserPreferences salvo instrucción explícita.
- RESPETAR estrictamente la arquitectura existente del proyecto.
- NO introducir dependencias nuevas sin justificar dentro del mismo bloque.

INCUMPLIMIENTO
- CUALQUIER RESPUESTA QUE NO CUMPLA ESTE FORMATO SE CONSIDERA INVÁLIDA.

10) PATRÓN OBLIGATORIO: AJAX + Modal para Eliminaciones

REFERENCIA COMPLETA: Ver archivo AJAX_DELETION_PATTERN.md

Resumen obligatorio para TODAS las eliminaciones:

Componentes requeridos:
1. Template: Botón .btn-eliminar-objeto + Modal Bootstrap + {% csrf_token %}
2. JavaScript: AJAX en {% block extra_js %} con delegación de eventos
3. Vista: JsonResponse detectando solicitud AJAX de forma robusta

Reglas técnicas:
- El Modal de eliminación debe tener ID único por página.
- Si solo existe un listado en la vista, puede usarse deleteModal.
- Si existen múltiples componentes reutilizables o partials, el ID debe incluir prefijo contextual.
- Está PROHIBIDO generar IDs duplicados en el DOM.
- La vista debe detectar AJAX usando:
  - Header X-Requested-With: XMLHttpRequest
  O
  - Header Accept: application/json
  O
  - Parámetro ?ajax=1
- Siempre retornar JsonResponse cuando se detecte solicitud AJAX.
- Usar transaction.atomic() en la vista.
- Incluir spinner durante procesamiento.
- Mostrar Toast de éxito/error usando sistema i18n.
- Todos los textos deben incluir data-key.

Referencia oficial:
- Template: access_control/templates/access_control/usuarios_lista.html
- Vista: access_control/views.py (clase UsuarioEliminarView)

Este es el patrón OFICIAL del sistema. Aplicar a TODOS los listados con eliminación.
