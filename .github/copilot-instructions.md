# Global repository instructions

- Make minimal, backward-compatible changes that respect the existing architecture.
- Preserve multi-company isolation and use the active company from the session.
- Respect the existing access_control and ICMEAS permission system.
- Never expose secrets, credentials, tokens, or passwords.
- Do not modify Docker, Nginx, or production configuration unless explicitly requested.
- Do not create models, migrations, or broad refactors outside the requested scope.
- Run focused tests and `python manage.py check` when applicable.
- Do not unnecessarily convert a traditional HTML POST flow to AJAX or fetch.
- Treat `static/js/app.js` as immutable template/vendor code: do not modify, patch, reformat, minify, or use it for new functionality.
- If a solution appears to require changing `static/js/app.js`, stop and propose an external alternative before editing.
- Consult specialized documentation in `COPILOT/` only when the task requires it; do not read the entire directory by default.
