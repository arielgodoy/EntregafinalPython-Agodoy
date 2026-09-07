# Quickstart: Tareas Internas

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Guía de validación ejecutable de la feature. Los detalles de campos y rutas están en
[data-model.md](data-model.md) y [contracts/web-urls.md](contracts/web-urls.md); aquí solo
se describen escenarios de verificación end-to-end.

> **PENDIENTE DE AUTORIZACIÓN EXPRESA**: antes de ejecutar estos pasos, el registro de la
> app (`AppDocs/app_classification.py`, `INSTALLED_APPS`, `AppDocs/urls.py`) debe ser
> autorizado expresamente por el usuario. La elección de app nueva NO constituye dicha
> autorización.

## Prerequisitos

1. Entorno local del proyecto activo (venv, dependencias ya instaladas según README).
2. Migraciones aplicadas:
   ```powershell
   python manage.py migrate
   ```
3. El mecanismo de registro de vistas ICMEAS/menú para la app `tareas` se verifica durante
   la implementación (T026); cualquier seed o cambio en SYSTEM_APPS requiere autorización
   expresa previa. No ejecutar comandos de seed sin esa verificación y autorización.
4. Un usuario con empresa activa en sesión y permiso ICMEAS sobre las vistas `Tareas - *`
   (o un usuario sin permiso para verificar el 403, según escenario).

## Validación automatizada

```powershell
python manage.py test tareas --settings=AppDocs.settings_test
python manage.py check
```

Resultado esperado: todos los tests de `tareas/tests/` pasan; `check` sin errores nuevos.

## Escenarios manuales end-to-end

Levantar el servidor local (task "Django: Runserver (local)") y verificar:

### E1. Crear borrador mínimo (FR-001, FR-003, FR-005)

1. Login → empresa activa seleccionada.
2. Menú → "Tareas" → Crear. Ingresar solo título → Guardar.
3. **Esperado**: tarea visible en el listado con estado "Borrador", fecha de creación de hoy,
   empresa = empresa activa.

### E2. Borrador indefinido y edición (FR-006, FR-009)

1. Editar el borrador: cambiar descripción/prioridad/responsable → Guardar.
2. **Esperado**: sigue en "Borrador", sin fecha de publicación; sin límite de tiempo.

### E3. Publicación bloqueada sin responsable (FR-007)

1. Quitar el responsable del borrador → intentar Publicar.
2. **Esperado**: rechazo con mensaje claro; la tarea permanece en "Borrador".

### E4. Publicación exitosa (FR-008)

1. Asignar un responsable activo → Publicar.
2. **Esperado**: estado "Publicada", fecha de publicación registrada y visible en el detalle.

### E5. Publicación irreversible + responsable obligatorio (Q2, FR-008)

1. En la tarea publicada: verificar que NO existe acción "volver a borrador".
2. Intentar editar dejando el responsable vacío.
3. **Esperado**: error de validación; la tarea conserva responsable y fecha de publicación.

### E6. Aislamiento multiempresa (FR-003, FR-010)

1. Cambiar la empresa activa a otra empresa del usuario.
2. **Esperado**: el listado no muestra las tareas de la empresa anterior; el acceso directo
   por URL a una tarea de otra empresa responde 404.

### E7. ICMEAS / 403 (FR-011)

1. Con un usuario sin `Permiso.ingresar` en `Tareas - Listado`: la entrada de menú es visible,
   pero al acceder responde **403** con la página que permite solicitar acceso.

## Fuera de alcance en esta versión

- Eliminación de tareas (sin ruta, modal ni permiso `eliminar`).

## Verificación de cierre

```powershell
git diff --check
git status --short
```

Esperado: diff sin errores de whitespace; cambios de código limitados a `tareas/` y `specs/`.
Los cambios de registro en `AppDocs/app_classification.py`, `AppDocs/settings.py` y
`AppDocs/urls.py` solo pueden aparecer si el usuario otorgó autorización expresa previa.
Sin commit ni push sin autorización expresa del usuario.
