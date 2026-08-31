# Arquitectura y Apps Protegidas

La fuente tecnica de verdad para la clasificacion de apps es
`AppDocs/app_classification.py`. La documentacion no duplica esas listas.

## Clasificacion

- `SYSTEM_APPS`: infraestructura base compartida.
- `CORE_SYSTEM_APPS`: infraestructura transversal critica dentro de `SYSTEM_APPS`.
- `SYSTEM_SUPPORT_APPS`: infraestructura transversal no critica dentro de `SYSTEM_APPS`.
- `APPLICATION_APPS`: modulos de negocio.

## Lectura y escritura

Copilot puede leer archivos, buscar referencias, auditar, diagnosticar,
revisar Git, ejecutar tests y consultar codigo o configuracion de una
`SYSTEM_APP` sin autorizacion adicional.

Copilot no puede editar, crear, eliminar, mover, renombrar ni refactorizar
archivos dentro de una `SYSTEM_APP` sin autorizacion expresa del usuario en la
tarea actual. Esto incluye models, views, services, decorators, middleware,
urls, forms, serializers, templates, JavaScript, CSS, migrations, management
commands, seeds, tests, admin, signals y utils.

La autorizacion debe identificar la `SYSTEM_APP` y el archivo o alcance
concreto. No autoriza otros archivos, otras apps ni tareas futuras.

## Cambios transversales

Si una tarea cuyo objetivo principal pertenece a una `APPLICATION_APP` requiere
modificar una `SYSTEM_APP`, Copilot debe detener la escritura en la app
protegida e identificar la app, los archivos exactos, el motivo, el impacto
transversal y el riesgo. Solo puede continuar con autorizacion expresa.
La lectura y el diagnostico pueden continuar.

## Proteccion reforzada para CORE_SYSTEM_APPS

Antes de modificar una `CORE_SYSTEM_APP` expresamente autorizada, Copilot debe:

1. Releer `COPILOT/INDICE.md`.
2. Confirmar la autorizacion concreta.
3. Enumerar los archivos CORE autorizados.
4. Explicar el impacto transversal y revisar dependencias relevantes.
5. Aplicar el cambio minimo y ejecutar pruebas especificas y regresiones relacionadas.
6. Ejecutar `git diff --check` y revisar el diff final completo.
7. No hacer commit ni push sin autorizacion expresa.

## Deuda arquitectonica conocida

- `api -> biblioteca`: una app SYSTEM importa el modelo `Propietario`.
- `control_de_proyectos <-> control_operacional`: ciclo entre apps de negocio.
- `auditoria`: conoce explicitamente Biblioteca y Gestion DTE.

Estas deudas se registran para planificacion futura y no autorizan cambios
transversales por si mismas.
