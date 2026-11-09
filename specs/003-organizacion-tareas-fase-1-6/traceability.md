# Trazabilidad y cierre documental Fase 1.6

Fecha: 2026-10-30. Baseline: `main`,
`196658dfb4d77b3942bde1603e1affa00fc112d2`.
**Resultado**: SI, CON CONDICIONES para iniciar bloques independientes autorizados;

## Rectificación arquitectónica — 2026-11-09

FR23 y FR31-FR36 se consideran implementables en su capa SQL target mediante DDL
MySQL y servicios dentro de `tareas`. Las columnas de estado de la matriz que
mencionan G17/G18/G19 deben leerse como gates de transición, callers, writers,
membresías y certificación, no como impedimento para diseñar o probar el esquema
aislado. La fuente única solo queda cerrada después de T224-T226 y la certificación
de consistencia; no se habilita dual writer.
no es cierre de implementacion ni certificacion de lote multi-base.

## Matriz requisito -> decision -> contrato -> implementacion -> prueba

La correspondencia bidireccional con la SPEC MAESTRA, FR-P06, tareas historicas,
interfaces SYSTEM y el orden de implementacion se mantiene en
[synchronization.md](synchronization.md). Esta matriz cubre ahora 36 requisitos y
61 tareas, conservando IDs y estados historicos.

Abreviaturas de documentos (enlaces relativos):
[S](spec.md), [D](data-model.md), [P](plan.md),
[O](contracts/organizacion.md), [T](contracts/tareas.md),
[C](contracts/consistencia.md), [R](research.md),
[Q](quickstart.md), [Tasks](tasks.md).
Decisiones F16-Dxx y gates F16-Gxx estan en R; todos los AC en Q.
Estado "nuevo" = documentado, NO implementado. "Base" = solo la parte preexistente.

| ID | Requisito | Decision aprobada/origen | Documento | Owner | Estado | Tareas / prueba prevista |
|---|---|---|---|---|---|---|
| F16-FR01 | Local/Departamento por Empresa en BASE_TAREAS | F16-D01/D13/D17/D19; T092/T093 | S,D,O,C | tareas nueva funcionalidad; modelos organizacion preservados | Target aprobado; G19 y corte pendientes | T213-T220,T212,T215; F16-AC39/41 |
| F16-FR02 | Membresia multiple y unica por triple | F16-D02; prompt 4.2 | S,D,O | organizacion | Nuevo | T172-T179; F16-AC03/04 |
| F16-FR03 | Roles organizacionales y maximo JEFE | F16-D02; prompt 4.2; precisa FR-D06 | S,D,O | dominio existente; nueva orquestacion tareas | Historia preservada; T182 bloqueada G19 | T173,T182; F16-AC07/08 |
| F16-FR04 | Vigencia e historia | F16-D02; prompt 4.2/8 | S,D,O | organizacion existente | T176/T179 historicas; no cert BASE_TAREAS | T176,T179; F16-AC05/06/07 |
| F16-FR05 | Sustitucion explicita JEFE | F16-D03; prompt 4.3 | S,O,C | tareas consume API organizacional | G19/G01/G02 | T177,T182; F16-AC07/08 |
| F16-FR06 | Maestro protegido | F16-D12/D16; prompt 4.4 | S,O | tareas | Nombre aprobado, superficie parcial; CRUD bloqueado por APIs | T180-T186,T212,T220,T223; F16-AC29/36/39 |
| F16-FR07 | Opcion B en tres ambitos | F16-D04; prompt 5 | S,T | tareas consume organizacion | Nuevo | T187-T190,T193; F16-AC01/09/10/11 |
| F16-FR08 | Validaciones acumulativas | F16-D04; prompt 5.1; FR-D12 | S,T,C | tareas / APIs SYSTEM | Extension | T188-T190,T193; F16-AC01/18/19 |
| F16-FR09 | Lectura y limites del gate | F16-D04/D05; prompt 5.2 | S,T | tareas | Nuevo, preservacion existente | T187,T190,T193; F16-AC02/28/29 |
| F16-FR10 | Traslado y lista de revision | F16-D05; prompt 6.1 | S,O,T | organizacion + tareas, sin ciclo | Nuevo | T176,T191,T192; F16-AC03/12 |
| F16-FR11 | Perdida sin borrar participantes | F16-D05; prompt 6.2 | S,T | tareas | Nuevo; eventos G04 | T189-T193; F16-AC02/05/28 |
| F16-FR12 | Recuperacion sin deshacer cambios | F16-D05; prompt 6.3 | S,O,T | organizacion + tareas | Nuevo; eventos G04 | T176,T192,T193; F16-AC06/28 |
| F16-FR13 | Baja departamental condicionada | F16-D06/D16; prompt 6.4 | S,T,C | tareas coordina; escritura via API publica | G19/T201/G07 bloquean baja | T183,T184,T201,T220,T223,T226; F16-AC13/14/32/39 |
| F16-FR14 | Jerarquia e historia cerrada | F16-D06; prompt 6.4/6.5; FR-E02 | S,T,C | tareas | Preservacion | T190,T201,T208; F16-AC15/28 |
| F16-FR15 | Reactivacion revalidada | F16-D05/D06; prompt 6.5 | S,O,C | organizacion + tareas | Nuevo | T183,T201,T208; F16-AC06/31 |
| F16-FR16 | Regularizacion individual | F16-D07; prompt 7.1/7.2; FR-D08..17 | S,T | tareas | Base responsable; extension | T198,T200,T205; F16-AC18/34 |
| F16-FR17 | Manifiesto de lote acotado | F16-D07; prompt 7.3 | S,T,D | tareas | Nuevo; roles G03 | T171,T194-T200; F16-AC16/33 |
| F16-FR18 | Preview completo sin escritura | F16-D07; prompt 7.4 | S,T | tareas | Nuevo | T197,T202,T205; F16-AC17/26 |
| F16-FR19 | Confirmacion/revalidacion | F16-D07/D10; prompt 7.3/7.5 | S,T,C | tareas | Nuevo | T197,T199,T202; F16-AC19/20/26 |
| F16-FR20 | Todo-o-nada operacional | F16-D08; prompt 7.5 | S,C | tareas/BASE_TAREAS | Solo atomicidad individual actual | T198,T199,T205; F16-AC16/17/21/22 |
| F16-FR21 | Evidencia por tarea y UUID | F16-D08; prompt 8 | S,D,T,C | tareas | Nuevo | T195,T196,T203; F16-AC16/23/27/34 |
| F16-FR22 | Notificar tras exito completo | F16-D08/D11; prompt 7.3/9; T054 | S,T,C | tareas -> notificaciones/acounts | Extension | T204,T205; F16-AC24/25/27 |
| F16-FR23 | Maestros en BASE_TAREAS; nueva funcionalidad en tareas | F16-D13/D17/D19/D20; decision 2026-11-03 | S,D,C,R | tareas; otros owners read-only | Objetivo aprobado; G17-G19 bloquean | T213-T220,T224-T226; F16-AC30/40/41 |
| F16-FR24 | Concurrencia de membresia | F16-D10 tecnico; prompt 7.5 exige propiedad | S,C | organizacion + tareas | Diseno; G01/G07 | T177,T199,T201,T207; F16-AC08/14/20/32 |
| F16-FR25 | Auditorias separadas/no shadow | F16-D11/D18; prompt 8 | S,D,T,C,R | owners/auditoria | G02; no atomicidad multi-base | T170,T176,T203,T216,T218-T220; F16-AC07/22/23/42 |
| F16-FR26 | Compatibilidad y arranque | F16-D12; prompt 5.2/6/11 | S,D,P,Q | organizacion + tareas | Nuevo gate despliegue | T174,T193,T208,T210; F16-AC11/28/35 |
| F16-FR27 | Errores/replay seguros | F16-D08/D11; prompt 7.5/10 y reglas base | S,T,C | tareas | Extension | T199,T203-T205; F16-AC21/23/25/27/30 |
| F16-FR28 | Canales oficiales | F16-D11; prompt 9; T054 | S,T | tareas -> SYSTEM | Base preservada; G04 organizacional | T171,T192,T204; F16-AC06/24/25 |
| F16-FR29 | UX, i18n y 403 oficiales | F16-D12; instrucciones y prompt 3/4.4 | S,O,T,P | tareas + dependencia externa | Nuevo UI; G05 | T180-T186,T202,T209; F16-AC29/36 |
| F16-FR30 | Trazabilidad/validacion | F16-D12/D18; prompt 12/13/14 | P,Q,Tasks,R | entrega documental + owners futuros | Documento; tests no ejecutados | T170,T206-T211,T225-T227; F16-AC01 a F16-AC42 |
| F16-FR31 | Proveedores globales, RUT e identidad unica | F16-D13/D14/D19/D20; decision 2026-11-03 | S,D,T,R | tareas; API Proveedores faltante | G17 bloquea; no duplicar modelo | T213-T218,T221,T224-T226; F16-AC37/40-42 |
| F16-FR32 | Locales por Empresa y proteccion ERP | F16-D13/D15/D19/D20; decision 2026-11-03 | S,D,O,T,R | tareas; API Local faltante | G18/T227 bloquean; owner legado intacto | T213-T215,T216-T219,T222,T224-T227; F16-AC38/40-42 |
| F16-FR33 | Departamentos por Empresa y lifecycle T183 | F16-D13/D16/D19/D20; decision 2026-11-03 | S,D,O,T,C,R | tareas consume API organizacional | G19/T201/G07 bloquean lifecycle | T212,T213-T220,T223-T226; F16-AC39-42 |
| F16-FR34 | Autonomía de `tareas` frente a otras APPLICATION APPS | Addendum de autonomía 2026-11-09; F16-D19/D20 | S,P,O,T,C,R | tareas | Diseño aprobado; certificación de imports pendiente | T214,T224,T225; F16-AC40-42 |
| F16-FR35 | Validación Python interna de RUT | Addendum 2026-11-09; F16-D21 | S,D,T,R | tareas | Implementación certificada; mutaciones aún bloqueadas | T218,T228,T225; F16-AC37/40-42 |
| F16-FR36 | Registro técnico durable e idempotencia de mutaciones | Addendum 2026-11-09; F16-D18/D22 | S,D,T,C,R | tareas/BASE_TAREAS + auditoría central | Registro SQL e idempotencia certificadas; integración/auditoría central pendiente | T216,T229,T230,T225; F16-AC23/27/30/40-42 |

## Estado de calidad documental

- 36 requisitos con IDs exclusivos, decision/fuente, owner, documento, tarea y
  escenario previsto. Ningun requisito nuevo sin trazabilidad.
- 61 tareas totales: 10 completadas historicamente y 51 pendientes, con path,
  dependencias y criterio de aceptacion. Ninguna tarea nueva se marca implementada.
- 42 escenarios verificables; los escenarios agregados no se ejecutaron ni se
  registran como PASS.
- Estados/roles funcionales/VICMEAS originales se referencian, no se redefinen.
- No jerarquia Local -> Departamento ni dependencia circular; Empresa de sesion.
- Modelo, tres contratos, riesgos/gates y estrategia de recuperacion documentados.
- En la consolidacion anterior, contradicciones historicas identificadas/resueltas
  para ese scope en research, sin editar maestras. La sincronizacion posterior
  agrega enlaces y precisiones autorizadas en 001; no toca documentos protegidos.
- La rectificacion de ownership identifica incompatibilidad concreta: las APIs
  publicas necesarias no existen para parte del CRUD; G17-G19 bloquean esas acciones.
  No se oculta la dependencia ni se declara completo el dominio.

## Limites del cierre

La consolidacion de las decisiones **expresamente aprobadas** esta representada.
La Fase 1.6 puede iniciar persistencia/consultas y otras partes independientes tras
autorizacion de codigo; no puede declararse lista para habilitacion integral hasta:

1. Resolver F16-G02 para auditoria/proyeccion multi-base y Proveedores, G03
   (roles no soportados) y G04 (notificaciones organizacionales no especificadas).
2. Certificar G01/G07 (concurrencia/baja entre bases), G06 (schema remoto).
3. Obtener autorizaciones G05 y preparar G08 (altas explicitas previas al gate).
4. Verificar los escenarios, rollback, replay y efectos posteriores G09.
5. Resolver G17-G19 con APIs publicas autorizadas; si requieren cambios fuera de
   `tareas`, detener la operacion y pedir autorizacion separada. No usar modelos
   privados ni catalogos paralelos para cerrar la matriz.

No hay un documento omitido ni un placeholder que suplante una decision:
los contratos tienen secciones acotadas pendientes explicitamente identificadas.
No afirmar "contrato integral sin condiciones" ni "implementacion terminada".

## Validacion de la consolidacion anterior

Control final exigido: lectura completa del diff de los nuevos documentos,
verificacion de enlaces relativos/IDs/dependencias/CA, `git diff --check` y
`git status --short --untracked-files=all`. Para archivos nuevos sin stage, el
diff normal no muestra contenido: revisar cada uno con `git diff --no-index`
contra un archivo vacio y comprobar whitespace tambien sobre ese diff.

Estado esperado: HEAD/rama iguales, cero archivos versionados anteriores
modificados, solo los diez documentos de este directorio como nuevos y el respaldo
SQLite preexistente intacto. Nada de codigo, migraciones, datos, infraestructura,
commits, push ni cambios fuera de `specs/`.

## Validacion de la sincronizacion posterior

La [matriz de sincronizacion](synchronization.md) amplía ese baseline: permite
los cambios documentales necesarios en 001 y 003, preservando IDs/checkboxes y
dependencias. El control de cero modificaciones versionadas del apartado anterior
corresponde a la primera entrega, no a la sincronizacion solicitada despues.
FR-P06 permanece sin cambios; F16-FR01 a F16-FR30 conservan IDs y se agregan
F16-FR31 a F16-FR36.
SYNC-C01 deja pendiente el orden tecnico T199/T200, sin ocultarlo ni afectar el
bloque T170/T172-T175. Ninguna tarea nueva pasa a ejecutada y SYSTEM sigue intacto.

## Trazabilidad de la arquitectura C y ownership — 2026-11-03

T176/T177 permanecen completadas historicamente para sus garantias en `default`;
no son certificacion de `BASE_TAREAS`. T181, T183, T184 y T212 siguen pendientes.
T201/G07 sigue siendo gate obligatorio antes de habilitar baja departamental.
Los IDs T213-T227 asignan nueva implementacion a `tareas`, documentan dependencias
publicas, gates G17-G19, pantallas, consumidores, certificacion y corte. Las APIs
faltantes mantienen esas tareas bloqueadas; no se modifican apps fuente bajo esta
autorizacion. Ningun estado completado se reabre ni se usa como evidencia de
migracion productiva.
