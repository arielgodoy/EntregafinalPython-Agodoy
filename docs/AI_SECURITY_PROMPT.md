================= PROMPT DE ANALISIS DE SEGURIDAD =================

REGLA N°0
Respetar COPILOT_RULES.md y AI_CONTEXT_SYSTEM.md.

FORMATO
Texto simple, sin HTML ni Markdown.

----------------------------------------------------------------------------

OBJETIVO

Evaluar riesgos de seguridad en código Django multiempresa.

----------------------------------------------------------------------------

VERIFICAR SIEMPRE

- Validación de permisos
- Scoping por empresa
- Acceso a datos sensibles
- Exposición de endpoints
- Escalamiento de privilegios
- Inyección de datos
- Filtrado por empresa_id

----------------------------------------------------------------------------

ENTREGAR

1) Riesgos detectados
2) Severidad
3) Ubicación
4) Escenario de explotación
5) Mitigación recomendada

===========================================================================
