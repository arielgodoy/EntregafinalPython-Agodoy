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
