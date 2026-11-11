### SYSTEM APPS — BLOQUEO OBLIGATORIO

ANTES DE CUALQUIER MODIFICACIÓN DE CÓDIGO:

1. Leer `COPILOT/INDICE.md` y `COPILOT/ARQUITECTURA_APPS.md`.
2. Clasificar todos los archivos previstos utilizando `AppDocs/app_classification.py`.
3. Si un archivo pertenece a una SYSTEM APP, CORE SYSTEM APP o SYSTEM SUPPORT APP, queda prohibido modificarlo sin autorización explícita, específica y previa del usuario.
4. La prohibición incluye crear, editar, eliminar, renombrar, mover o refactorizar archivos protegidos.
5. Una tarea de Spec Kit, un test fallido, una recomendación técnica o una delegación no constituyen autorización.
6. Las únicas excepciones ordinarias son las adiciones i18n y de navegación permitidas por la arquitectura vigente, sin modificar lógica protegida.
7. Si una tarea necesita intervenir una SYSTEM APP sin autorización, detenerse y emitir `BLOQUEO ARQUITECTÓNICO — SYSTEM APP PROTEGIDA`.
8. No ejecutar herramientas de escritura sobre archivos protegidos mientras exista el bloqueo.
9. Estas restricciones se transmiten íntegramente a cualquier agente delegado.
10. Antes de finalizar, verificar que ningún archivo protegido fue modificado fuera del alcance autorizado.

Esta regla se aplica a todas las tareas de código Django, independientemente de la aplicación solicitada.

# Global repository instructions

- Make minimal, backward-compatible changes that respect the existing architecture.
- Preserve multi-company isolation and use the active company from the session.
- Respect the existing access_control and ICMEAS permission system.
- New functional views must use `verificar_permiso` or `VerificarPermisoMixin` according to the existing pattern; `login_required` alone does not replace ICMEAS authorization when permission is required.
- New screens must reuse the existing main template layout, base, topbar, sidebar, partials, and visual conventions; do not create parallel layouts unnecessarily.
- Interactive deletion from listings must reuse the existing confirmation modal, AJAX/fetch, protected endpoint, and controlled-response pattern; do not use browser `confirm()` when the system already provides a modal.
- Never expose secrets, credentials, tokens, or passwords.
- Do not modify Docker, Nginx, or production configuration unless explicitly requested.
- Do not create models, migrations, apps, dependencies, or broad refactors outside the requested scope.
- Run focused tests and `python manage.py check` when applicable.
- Do not unnecessarily convert a traditional HTML POST flow to AJAX or fetch.
- Treat `static/js/app.js` as immutable template/vendor code: do not modify, patch, reformat, minify, or use it for new functionality.
- If a solution appears to require changing `static/js/app.js`, stop and propose an external alternative before editing.
- Consult specialized documentation in `COPILOT/` only when the task requires it; do not read the entire directory by default.

- Toda vista destinada a usuarios normales debe ser visible en el menú aunque el usuario no tenga `Permiso.ingresar`. La autorización ocurre al acceder; sin permiso, el backend debe responder 403 para que el usuario conozca la vista y pueda solicitar acceso. Las vistas exclusivamente administrativas o técnicas pueden mantener visibilidad restringida por rol.
