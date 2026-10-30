# Trazabilidad y cierre documental Fase 1.6

Fecha: 2026-10-30. Baseline: `main`,
`196658dfb4d77b3942bde1603e1affa00fc112d2`.
**Resultado**: SI, CON CONDICIONES para iniciar bloques independientes autorizados;
no es cierre de implementacion ni certificacion de lote multi-base.

## Matriz requisito -> decision -> contrato -> implementacion -> prueba

La correspondencia bidireccional con la SPEC MAESTRA, FR-P06, tareas historicas,
interfaces SYSTEM y el orden de implementacion se mantiene en
[synchronization.md](synchronization.md). Esta matriz sigue siendo la cobertura
interna de los mismos 30 requisitos y 42 tareas, sin duplicarlos ni renumerarlos.

Abreviaturas de documentos (enlaces relativos):
[S](spec.md), [D](data-model.md), [P](plan.md),
[O](contracts/organizacion.md), [T](contracts/tareas.md),
[C](contracts/consistencia.md), [R](research.md),
[Q](quickstart.md), [Tasks](tasks.md).
Decisiones F16-Dxx y gates F16-Gxx estan en R; todos los AC en Q.
Estado "nuevo" = documentado, NO implementado. "Base" = solo la parte preexistente.

| ID | Requisito | Decision aprobada/origen | Documento | Owner | Estado | Tareas / prueba prevista |
|---|---|---|---|---|---|---|
| F16-FR01 | Maestros separados por Empresa | F16-D01; prompt 4.1; T092/T093 | S,D,O | organizacion | Base preservada | T172-T175; F16-AC09/15 |
| F16-FR02 | Membresia multiple y unica por triple | F16-D02; prompt 4.2 | S,D,O | organizacion | Nuevo | T172-T179; F16-AC03/04 |
| F16-FR03 | Roles organizacionales y maximo JEFE | F16-D02; prompt 4.2; precisa FR-D06 | S,D,O | organizacion | Nuevo | T173,T182; F16-AC07/08 |
| F16-FR04 | Vigencia e historia | F16-D02; prompt 4.2/8 | S,D,O | organizacion | Nuevo; G02 | T176,T179; F16-AC05/06/07 |
| F16-FR05 | Sustitucion explicita JEFE | F16-D03; prompt 4.3 | S,O,C | organizacion | Nuevo; G01/G02 | T177,T182; F16-AC07/08 |
| F16-FR06 | Maestro protegido | F16-D12; prompt 4.4 | S,O | tareas UI / organizacion dominio | Nombre aprobado, superficie ausente | T180-T186; F16-AC29/36 |
| F16-FR07 | Opcion B en tres ambitos | F16-D04; prompt 5 | S,T | tareas consume organizacion | Nuevo | T187-T190,T193; F16-AC01/09/10/11 |
| F16-FR08 | Validaciones acumulativas | F16-D04; prompt 5.1; FR-D12 | S,T,C | tareas / APIs SYSTEM | Extension | T188-T190,T193; F16-AC01/18/19 |
| F16-FR09 | Lectura y limites del gate | F16-D04/D05; prompt 5.2 | S,T | tareas | Nuevo, preservacion existente | T187,T190,T193; F16-AC02/28/29 |
| F16-FR10 | Traslado y lista de revision | F16-D05; prompt 6.1 | S,O,T | organizacion + tareas, sin ciclo | Nuevo | T176,T191,T192; F16-AC03/12 |
| F16-FR11 | Perdida sin borrar participantes | F16-D05; prompt 6.2 | S,T | tareas | Nuevo; eventos G04 | T189-T193; F16-AC02/05/28 |
| F16-FR12 | Recuperacion sin deshacer cambios | F16-D05; prompt 6.3 | S,O,T | organizacion + tareas | Nuevo; eventos G04 | T176,T192,T193; F16-AC06/28 |
| F16-FR13 | Baja departamental condicionada | F16-D06; prompt 6.4 | S,T,C | organizacion; tareas coordina | Nuevo; G07 | T183,T184,T201; F16-AC13/14/32 |
| F16-FR14 | Jerarquia e historia cerrada | F16-D06; prompt 6.4/6.5; FR-E02 | S,T,C | tareas | Preservacion | T190,T201,T208; F16-AC15/28 |
| F16-FR15 | Reactivacion revalidada | F16-D05/D06; prompt 6.5 | S,O,C | organizacion + tareas | Nuevo | T183,T201,T208; F16-AC06/31 |
| F16-FR16 | Regularizacion individual | F16-D07; prompt 7.1/7.2; FR-D08..17 | S,T | tareas | Base responsable; extension | T198,T200,T205; F16-AC18/34 |
| F16-FR17 | Manifiesto de lote acotado | F16-D07; prompt 7.3 | S,T,D | tareas | Nuevo; roles G03 | T171,T194-T200; F16-AC16/33 |
| F16-FR18 | Preview completo sin escritura | F16-D07; prompt 7.4 | S,T | tareas | Nuevo | T197,T202,T205; F16-AC17/26 |
| F16-FR19 | Confirmacion/revalidacion | F16-D07/D10; prompt 7.3/7.5 | S,T,C | tareas | Nuevo | T197,T199,T202; F16-AC19/20/26 |
| F16-FR20 | Todo-o-nada operacional | F16-D08; prompt 7.5 | S,C | tareas/BASE_TAREAS | Solo atomicidad individual actual | T198,T199,T205; F16-AC16/17/21/22 |
| F16-FR21 | Evidencia por tarea y UUID | F16-D08; prompt 8 | S,D,T,C | tareas | Nuevo | T195,T196,T203; F16-AC16/23/27/34 |
| F16-FR22 | Notificar tras exito completo | F16-D08/D11; prompt 7.3/9; T054 | S,T,C | tareas -> notificaciones/acounts | Extension | T204,T205; F16-AC24/25/27 |
| F16-FR23 | Separacion de bases/IDs | F16-D09; prompt 3/10; connection-roles | S,D,C | cada owner | Patron existente, extension | T175,T188,T196,T206; F16-AC04/30 |
| F16-FR24 | Concurrencia de membresia | F16-D10 tecnico; prompt 7.5 exige propiedad | S,C | organizacion + tareas | Diseno; G01/G07 | T177,T199,T201,T207; F16-AC08/14/20/32 |
| F16-FR25 | Auditorias separadas/no shadow | F16-D11; prompt 8 | S,D,T,C | organizacion/tareas/auditoria | G02; deuda participantes existente | T170,T176,T203; F16-AC07/22/23 |
| F16-FR26 | Compatibilidad y arranque | F16-D12; prompt 5.2/6/11 | S,D,P,Q | organizacion + tareas | Nuevo gate despliegue | T174,T193,T208,T210; F16-AC11/28/35 |
| F16-FR27 | Errores/replay seguros | F16-D08/D11; prompt 7.5/10 y reglas base | S,T,C | tareas | Extension | T199,T203-T205; F16-AC21/23/25/27/30 |
| F16-FR28 | Canales oficiales | F16-D11; prompt 9; T054 | S,T | tareas -> SYSTEM | Base preservada; G04 organizacional | T171,T192,T204; F16-AC06/24/25 |
| F16-FR29 | UX, i18n y 403 oficiales | F16-D12; instrucciones y prompt 3/4.4 | S,O,T,P | tareas + dependencia externa | Nuevo UI; G05 | T180-T186,T202,T209; F16-AC29/36 |
| F16-FR30 | Trazabilidad/validacion | F16-D12; prompt 12/13/14 | P,Q,Tasks,R | entrega documental + owners futuros | Documento; tests no ejecutados | T170,T206-T211; F16-AC01 a F16-AC36 |

## Estado de calidad documental

- 30 requisitos con IDs exclusivos, decision/fuente, owner, documento, tarea y
  escenario previsto. Ningun requisito nuevo sin trazabilidad.
- 42 tareas pendientes con path, dependencias y criterio de aceptacion.
  Ninguna tarea marcada como implementada; ninguna sin criterio.
- 36 escenarios verificables; no se ejecutaron ni se registran como PASS.
- Estados/roles funcionales/VICMEAS originales se referencian, no se redefinen.
- No jerarquia Local -> Departamento ni dependencia circular; Empresa de sesion.
- Modelo, tres contratos, riesgos/gates y estrategia de recuperacion documentados.
- En la consolidacion anterior, contradicciones historicas identificadas/resueltas
  para ese scope en research, sin editar maestras. La sincronizacion posterior
  agrega enlaces y precisiones autorizadas en 001; no toca documentos protegidos.
- No se detecto una contradiccion funcional que exija redisenar el dominio.
  Persisten precisiones F16-G03/G04 y capacidad externa G02; no se las disfraza
  como contratos completos de funciones ya habilitables.

## Limites del cierre

La consolidacion de las decisiones **expresamente aprobadas** esta representada.
La Fase 1.6 puede iniciar persistencia/consultas y otras partes independientes tras
autorizacion de codigo; no puede declararse lista para habilitacion integral hasta:

1. Resolver F16-G02 (auditoria organizacional), G03 (roles no soportados) y G04
   (notificaciones organizacionales no especificadas).
2. Certificar G01/G07 (concurrencia/baja entre bases), G06 (schema remoto).
3. Obtener autorizaciones G05 y preparar G08 (altas explicitas previas al gate).
4. Verificar los escenarios, rollback, replay y efectos posteriores G09.

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
FR-P06 es el unico FR maestro nuevo; F16-FR01 a F16-FR30 permanecen sin renumerar.
SYNC-C01 deja pendiente el orden tecnico T199/T200, sin ocultarlo ni afectar el
bloque T170/T172-T175. Ninguna tarea pasa a ejecutada y SYSTEM sigue intacto.
