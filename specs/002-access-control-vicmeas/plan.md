# Implementation Plan: Control de acceso VICMEAS

## Resumen

La entrega actual combina una corrección productiva acotada con documentación y
gobernanza. El comportamiento productivo ya está
implementado en `access_control`; el plan registra el contrato y su validación sin
alterar código protegido.

## Contexto técnico

- Django 5.x con templates server-side.
- Empresa activa en `session['empresa_id']`.
- Autorización mediante `VerificarPermisoMixin` o `@verificar_permiso`.
- Sidebar calculado por `Permiso.ver`.
- Pruebas con `AppDocs.settings_test`.

## Diseño

1. Mantener `ver` como control exclusivo de visibilidad.
2. Mantener ICMEAS como control exclusivo de autorización backend.
3. Mantener la evaluación uniforme para `is_superuser`, sin bypass visual ni backend
  implícito; conservar la semántica explícita de `supervisor`.
4. Mantener operaciones del utilitario aditivas, transaccionales y acotadas por empresa.
5. Validar el contrato con las pruebas existentes de sidebar, mixin y utilitario.
6. Mantener `Notificaciones - Topbar` como dependencia SYSTEM explícita del shell/base:
  se incorpora por nombre canónico sin convertir el conjunto completo de ambiguas.

## Impacto

No se agregan modelos, migraciones, dependencias, URLs ni cambios de frontend. No se
modifican `access_control`, `specs/001-tareas-internas` ni archivos de infraestructura.

## Estrategia de validación

- Ejecutar pruebas focalizadas de VICMEAS, autorización y utilitario.
- Ejecutar `python manage.py check --settings=AppDocs.settings_test` si el entorno lo
  permite.
- Ejecutar `git diff --check`.
- Confirmar que el diff solo contiene la constitución y `specs/002-access-control-vicmeas`.
- Para el bootstrap actualizado, confirmar además que el cambio productivo se limita a
  `access_control/services/system_bootstrap.py` y su prueba focalizada.

## Contratos

Los contratos operativos no inventan REST API. Se documentan los comandos de bootstrap
y la interfaz web existente del Utilitario de Acceso en `contracts/`.