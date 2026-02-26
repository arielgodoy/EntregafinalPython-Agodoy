Lee y respeta obligatoriamente (ANTES de cualquier acción):
- docs/COPILOT_RULES.md
- docs/AI_CONTEXT_SYSTEM.md
- docs/AI_PROMPT_MASTER.md
- docs/AI_DEBUG_PROMPT.md
- docs/AI_SECURITY_PROMPT.md
- docs/AJAX_DELETION_PATTERN.md

OBJETIVO
Verificar que TODAS LAS VISTAS (HTML renderizadas) cumplan con la política i18n del proyecto:
- TODO texto visible en templates debe tener atributo data-key.
- No romper funcionalidad existente.
- No modificar app.js ni vendor/theme.
- No alterar lógica de permisos ni multiempresa.
- JSON responses NO requieren i18n.
- Cambios mínimos, directos y seguros.

ALCANCE
- Auditar todos los templates HTML usados por vistas del sistema (incluye parciales, modales, includes).
- Priorizar templates bajo /templates/ y dentro de cada app (*/templates/*).
- Excluir archivos de vendor/ y theme/ (solo lectura, NO modificar).

REGLAS DE i18n A VERIFICAR
1) Todo texto visible al usuario debe tener data-key:
   - Botones, labels, títulos, placeholders, tooltips, mensajes, links, textos dentro de <p>, <span>, <h1–h6>, etc.
2) No aplicar data-key a:
   - Texto generado dinámicamente desde variables ({{ variable }}) si no es literal.
   - Contenido puramente decorativo (íconos sin texto).
   - JSON, atributos aria-label ya internacionalizados por el theme si provienen de vendor.
3) Mantener claves existentes (NO renombrar masivamente).
4) Si falta data-key:
   - Agregar data-key="ruta.clave.sugerida" coherente con el contexto (app.vista.elemento).
5) Insertar UNA VEZ por archivo modificado el comentario obligatorio al inicio:
   <!-- ⚠️ TODO: Todos los textos visibles deben tener data-key para i18n -->