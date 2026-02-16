================= PROMPT DE DEBUGGING =================

REGLA N°0
Respetar COPILOT_RULES.md y AI_CONTEXT_SYSTEM.md.

FORMATO
Texto simple, sin HTML ni Markdown.

----------------------------------------------------------------------------

OBJETIVO

Diagnosticar fallos sin romper arquitectura.

----------------------------------------------------------------------------

PROCEDIMIENTO

1) Identificar causa raíz
2) Determinar si es problema de:
   - Permisos
   - Multiempresa
   - Configuración
   - Tests
   - Dependencias
   - Entorno

3) Indicar archivo y líneas afectadas
4) Proponer fix mínimo
5) Evaluar impacto sistémico

----------------------------------------------------------------------------

IMPORTANTE

NO proponer refactors grandes.
NO modificar seguridad.
NO omitir validaciones de permisos.

===========================================================================
