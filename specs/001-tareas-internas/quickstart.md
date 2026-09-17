# Quickstart: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Guía de validación ejecutable y progresiva. Los detalles de campos y rutas están en
[data-model.md](data-model.md) y [contracts/web-urls.md](contracts/web-urls.md); aquí solo
se describen escenarios de verificación end-to-end.

> **REGISTRO INICIAL RESUELTO**: el alta de la app en `AppDocs/app_classification.py`,
> `INSTALLED_APPS` y `AppDocs/urls.py` ya fue autorizada, ejecutada, testeada y versionada.
> Cualquier modificación futura adicional de esos archivos requiere una tarea separada con
> autorización y scope explícitos; no es una excepción al APPLICATION BOUNDARY.

## Prerequisitos

1. Entorno local del proyecto activo (venv, dependencias ya instaladas según README).
2. Migraciones de la fase habilitada aplicadas:
   ```powershell
   python manage.py migrate
   ```
3. El sidebar consume la infraestructura VICMEAS existente: `Permiso.ver` controla solo
   visibilidad por empresa activa y el mapping explícito de items a Vistas. No se agrega
   una implementación de VICMEAS en `tareas`; cualquier cambio futuro en SYSTEM_APPS
   requiere una tarea separada con autorización y scope explícitos.
4. Un usuario con empresa activa en sesión y permisos ICMEAS sobre las vistas `Tareas - *`
   para las acciones que probará, y `Permiso.ver` cuando deba verificar visibilidad.

## Validación automatizada por fase

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

### E7. VICMEAS e ICMEAS independientes (FR-011)

1. Con `Permiso.ver=True` y `Permiso.ingresar=True` en `Tareas - Listado`: el item aparece
   y el acceso funciona.
2. Con `Permiso.ver=True` y `Permiso.ingresar=False`: el item sigue visible, pero el
   backend responde **403** con la página que permite solicitar acceso.
3. Con `Permiso.ver=False` y `Permiso.ingresar=True`: el item no aparece, pero el acceso
   directo por URL funciona.
4. Con ambas banderas en `False`: el item no aparece y el acceso está prohibido.
5. Repetir la comprobación en dos empresas: `ver` en una empresa no hace visible el item
   en la otra. El superuser ve el sidebar completo por bypass visual, sin inferir bypass
   backend. Los padres aparecen solo si un hijo es visible.

## Validaciones del dominio por fases

### E8. Correlativos y estados (Phase 1)

- Crear un borrador y comprobar correlativo `A*` único por empresa.
- Publicar con responsable válido y comprobar conversión al correlativo `B*` sin nueva PK.
- Ejecutar transiciones permitidas y rechazar saltos de estado; verificar auditoría.
- Al marcar 100%, comprobar `cierre_completado == True` y estado `PENDIENTE_APROBACION_CIERRE`.
- Aprobar cierre y comprobar estado `CERRADA` con `cierre_completado == True`.
- Rechazar cierre y comprobar retorno a `GESTION` conservando `cierre_completado == True`;
   esta señal es lifecycle, no porcentaje general de avance.

### E9. Asignación y jerarquía (Phase 3)

- Crear padre, hijos y nietos dentro del máximo permitido (padre→hija→nieta, sin cuarto nivel).
- Anular el padre y comprobar que SOLO cambia `padre.anulada=True`; hijas/nietas conservan
  `anulada=False` y sus estados funcionales intactos, pero todas quedan anuladas
  efectivamente (lógica: tarea+padre+abuelo). Verificar notificación a participantes.
- Reactivar el padre y comprobar que SOLO cambia `padre.anulada=False`; los estados
  funcionales de toda la estructura siguen intactos (nunca cambiaron; no hay restauración).
- Confirmar que una hija anulada directamente (`anulada=True`) sigue anulada tras
  reactivar el padre.
- Confirmar que fechas afectadas quedan pendientes, sin recálculo automático.
- Bloqueo documentado: la notificación a participantes no está conectada desde
   `tareas`; queda pendiente de integración y no se implementa P1 Local en esta fase.

### E10. Hitos, mini-tareas y documentos (Phase 3)

- Validar `sum(cumplimiento * peso) / sum(pesos)` y redistribución al agregar un hito.
- Comprobar que mini-tareas pendientes bloquean cierre y no ponderan avance.
- Adjuntar documento/evidencia, cambiarlo y verificar historial y vencimiento informativo.

### E11. Cotizaciones (Phase 4)

- Crear o reutilizar proveedores del maestro local Django y abrir una `RondaCotizacion`.
- Crear cotizaciones asociadas a proveedores locales, conservando cotizaciones históricas con `proveedor=NULL` sin contarlas para el mínimo.
- Verificar máximo de 3 versiones por `(ronda, proveedor)`, mínimo por proveedores distintos y que varias versiones del mismo proveedor cuentan una sola vez.
- Confirmar que el cierre de ronda se bloquea hasta cumplir el mínimo y que cotizaciones vigentes de proveedores distintos permiten cerrarla.
- Marcar una cotización como `SELECCIONADA`, comprobar que el proveedor seleccionado es visible dentro de Django y que no se crea `Adjudicacion`.
- Reutilizar el cierre de Tarea vigente y validar que la ronda más reciente controla el mínimo.
- Confirmar que todo el flujo opera con el maestro local Django sin consultar ERP/legacy; la integración, conciliación y sincronización permanecen bloqueadas por P2.

Estado E11 PRE-P2: EJECUTADO/VALIDADO exclusivamente sobre las capacidades
internas autorizadas: rondas, mínimos, estados, fechas, observaciones,
documentos, histórico, selección interna, cierre controlado, nuevas rondas,
maestro local Django y versionado por `(ronda, proveedor)`.

Estado P2 ERP/legacy: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN. Quedan
fuera de esta validación la identidad externa del proveedor, lookup ERP,
validación ERP, conciliación, sincronización y actualización desde legacy.
No se declara identidad ERP ni se implementa integración legacy.

### E12. Colaboración, similitud y enlaces (Phase 5)

- Verificar notificaciones internas/email mediante mocks y reuniones de revisión.
- Comparar con tareas abiertas y cerradas usando 80% por defecto; cambiar umbral por empresa
   y comprobar que solo afecta evaluaciones nuevas.
- Abrir enlace como usuario autenticado de la empresa y rechazar acceso cross-company/externo.

Estado E12: EJECUTADO/VALIDADO mediante la regresión focal de colaboración,
similitud, enlaces y reuniones, con mocks de notificaciones/email y cobertura
de aislamiento cross-company.

### E13. Dashboards (Phase 6)

- Comprobar exactamente ocho KPI en cada dimensión permitida: estado, atrasadas, próximas a
   vencer, sin movimiento, aprobación pendiente, carga, cumplimiento y tiempo promedio de cierre.
- Verificar drill-down, paginación y aislamiento; mantener Local/Proveedor bloqueados sin legacy.

Estado E13: EJECUTADO/VALIDADO mediante la regresión integrada de KPI,
dashboards, T060, dashboard personal y metadata, manteniendo Local/Proveedor
fuera de las dimensiones de drill-down.

## Límites y bloqueos

- No hay eliminación física; se usa anulación auditada.
- P1 Local: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN; permanece `LEGACY API PENDIENTE`.
- P2 Proveedor: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN para integración,
  validación y conciliación con ERP legacy; el maestro Django local no queda bloqueado.
- No hay usuarios externos, plantilla de hitos ni vencimiento automático de documentos.
- El alta inicial ya está resuelta; cualquier modificación futura de `AppDocs/*` requiere
   autorización expresa.

## Verificación de cierre

```powershell
git diff --check
git status --short
```

### Gate permanente de i18n

Antes de cerrar cualquier cambio de UI en `tareas`, ejecutar el inventario y la
validación funcional en ambos idiomas. Una superficie solo está completa cuando
el `data-key` o `message_key` es correcto, existe en `static/lang/sp.json` y
`static/lang/en.json`, no es dinámico, los enums visibles tienen etiqueta i18n,
los mensajes backend/AJAX se resuelven y la pantalla fue comprobada en ES y EN.

El cierre requiere:

```powershell
python manage.py test tareas.tests.test_i18n --settings=AppDocs.settings_test
```

Y estas métricas en cero: `MISSING_SP`, `MISSING_EN`, `ONE_SIDE`, `DYNAMIC_KEYS`,
`RAW_MESSAGE_KEYS_VISIBLE` y `VISIBLE_HARDCODED_TEXT`, salvo excepciones
explícitamente justificadas y registradas. El inventario debe cubrir templates,
formularios, vistas, JavaScript app-local y ambos catálogos.

La comprobación manual mínima recorre sidebar, listado, crear/editar, detalle,
ciclo de vida, mis hitos y tareas, hitos, documentos/evidencias, cotizaciones,
reuniones, similitud, enlaces, dashboards y TO-DO si su UI está activa; debe
alternar ES → EN → ES sin reiniciar datos ni alterar la lógica.

Esperado: diff sin errores de whitespace; cambios de código limitados a `tareas/` y `specs/`.
Los cambios futuros adicionales en `AppDocs/app_classification.py`, `AppDocs/settings.py` y
`AppDocs/urls.py` sólo pueden aparecer en una tarea separada con autorización y scope
explícitos; desde este scope son dependencias externas.
Sin commit ni push sin autorización expresa del usuario.
