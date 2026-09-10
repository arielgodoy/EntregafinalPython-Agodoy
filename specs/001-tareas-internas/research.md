# Research: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md)

Las decisiones se mantienen dentro de `tareas/` y reutilizan interfaces existentes. No
quedan `NEEDS CLARIFICATION` para P4, P6 o P8. P1 y P2 siguen bloqueados por contrato
legacy, no por una decisión técnica pendiente dentro de la app.

## Decisions

### D1. Frontera y compatibilidad

- **Decision**: ampliar la app existente `tareas`, sin reutilizar ni modificar
  `control_de_proyectos.Tarea`.
- **Rationale**: ciclos y responsabilidades distintos; la Fase 1 debe conservar PK, URLs
  y comportamiento.
- **Alternatives considered**: fusionar modelos o mover el dominio a proyectos; rechazadas.

### D2. Seguridad, visibilidad y empresa activa

- **Decision**: consumir VICMEAS ya implementado: `Permiso.ver` controla exclusivamente
  la visibilidad del sidebar por usuario, Vista y `request.session['empresa_id']`;
  ICMEAS, `LoginRequiredMixin` cuando corresponda y la misma empresa activa protegen
  toda vista/acción. Validar cada queryset y objeto.
- **Rationale**: V/I son independientes y separan descubribilidad de autorización,
  evitando exposición cross-company sin convertir V en seguridad backend.
- **Alternatives considered**: permisos Django estándar, usar `ver` para autorizar
  acciones, hacer depender el menú de `ingresar`, o recibir la empresa por POST;
  rechazadas.

La decisión V independiente de I está cerrada y no se reabre en fases de `tareas`.
Los padres del sidebar se derivan de hijos visibles, el superuser tiene bypass visual
del sidebar únicamente, y el mapping item → Vista o clasificación GLOBAL pertenece a
la infraestructura base. La vista inicial sigue dependiendo de `ingresar=True`.

### D3. Persistencia incremental

- **Decision**: migraciones aditivas por fase, backfills idempotentes y activación gradual.
- **Rationale**: la Fase 1 contiene datos que deben conservarse mientras se agregan estados,
  relaciones y auditoría.
- **Alternatives considered**: reemplazo de `Tarea` o migración única; rechazadas.

### D4. Correlativos A/B

- **Decision**: un único registro cambia de A a B al publicar; unicidad por empresa y
  generación transaccional segura.
- **Rationale**: FR-A01/A06 exige transformación sin duplicación.
- **Alternatives considered**: tabla separada o duplicar al publicar; rechazadas.

### D5. Estados y auditoría

- **Decision**: servicio de transiciones explícitas, historial inmutable de origen/destino,
  usuario y fecha; anulación/reactivación separadas.
- **Rationale**: FR-C08/C09 y la restauración exacta requieren auditoría distinta del estado.
- **Alternatives considered**: cambios directos desde formularios; rechazados.

### D6. Jerarquía y anulación (REVISADO — diseño simplificado aprobado)

- **Decision**: la anulación usa un flag persistente `Tarea.anulada` (BooleanField,
  default False). `estado` representa SOLO el ciclo funcional (BORRADOR, ACTIVA, GESTION,
  PENDIENTE_APROBACION_CIERRE, CERRADA); `ANULADA` deja de ser estado canónico. La
  anulación jerárquica es LÓGICA (`anulada_efectivamente` = propia OR padre OR abuelo),
  NO una cascada física de escritura. Anular/reactivar solo cambia `anulada` de la tarea
  afectada; no modifica estados, responsables, participantes, correlativo ni relaciones.
- **Rationale**: elimina la cascada física y la necesidad de snapshot de estados para
  restaurar jerarquía; los datos nunca cambian, por lo que no hay nada que reconstruir.
- **Alternatives considered**: cascada física de estados ANULADA y snapshot de estructura
  para reactivación; rechazadas por duplicar fuente de verdad y complejidad.

### D7. Avance ponderado

- **Decision**: pesos relativos normalizados; `avance = sum(cumplimiento * peso) / sum(pesos)`.
  Agregar hitos actualiza el denominador sin alterar cumplimientos anteriores.
- **Rationale**: decisión P4.
- **Alternatives considered**: pesos fijos que suman 100 o pesos iguales; rechazadas.

### D8. Local y Proveedor legacy

- **Decision**: no crear maestros duplicados. Local solo se consumirá con contrato autorizado;
  Proveedor queda como referencia/adaptador pendiente, sin tabla, ID, API ni `rut_contable`.
- **Rationale**: FR-A07/J05/L06 y las restricciones explícitas.
- **Alternatives considered**: copiar datos o inferir claves; rechazadas.

### D9. Cotizaciones

- **Decision**: rondas históricas, mínimo configurable por ronda con default 3 y máximo de
  3 versiones por proveedor/ronda; el cierre verifica el mínimo.
- **Rationale**: P3 y FR-I01/I08.
- **Alternatives considered**: mínimo global o versiones ilimitadas; rechazadas.

### D10. KPI y consultas

- **Decision**: ocho KPI repetidos en dimensiones permitidas: total por estado, atrasadas,
  próximas a vencer, sin movimiento, esperando aprobación, carga abierta por responsable,
  cumplimiento y tiempo promedio de cierre.
- **Rationale**: P6 evita divergencias; Local/Proveedor no se habilitan sin legacy.
- **Alternatives considered**: KPI distintos por dimensión o métricas adicionales; rechazadas.

### D11. Similitud y enlaces

- **Decision**: comparar también tareas cerradas; umbral configurable por empresa con default
  80%, cambios solo para nuevas evaluaciones. Enlaces solo para usuarios autenticados, con
  ICMEAS, empresa activa y auditoría de acceso.
- **Rationale**: P8 y FR-N04/P03.
- **Alternatives considered**: umbral por usuario/tarea, enlaces públicos o convertir la tarea
  antigua; rechazadas.

### D12. Integraciones transversales

- **Decision**: consumir `notificaciones` y email de `acounts`; JS nuevo, si hace falta, vive
  en `tareas/`; no se editan vendor, apps consumidas ni templates globales.
- **Rationale**: FR-K04 y reglas de autocontención.
- **Alternatives considered**: subsistemas paralelos o editar `static/js/app.js`; rechazadas.

## Unresolved by design

- P1: contrato y elegibilidad de Local, `LEGACY API PENDIENTE`.
- P2: maestro/API/identidad de Proveedor, `LEGACY API PENDIENTE`.
- Registro técnico inicial de la app en los tres archivos `AppDocs/*`: resuelto, autorizado,
  ejecutado, testeado y versionado. Cualquier modificación futura adicional requiere
  autorización expresa.
