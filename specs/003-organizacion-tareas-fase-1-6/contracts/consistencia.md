# Consistencia, concurrencia y recuperacion

**Estado**: diseno tecnico pendiente de implementacion y certificacion.
No se cambia router, DATABASES ni infrastructure SYSTEM.

## Rectificación arquitectónica definitiva — 2026-11-09

Los tres maestros target son tablas MySQL InnoDB de `BASE_TAREAS`, creadas y
operadas por servicios SQL de `tareas`. Cada mutación debe validar Empresa activa
cuando aplique, unicidad, origen, estado y permisos; adquirir locks compatibles
con el índice afectado; y confirmar o revertir en una transacción MySQL. No hay
FK físicas ni JOINs cross-database.

Esta garantía local no equivale a 2PC con `default`, auditoría o correo. Los
fallos parciales entre bases deben dejar la operación explícitamente incierta,
reconciliable e inhabilitada para producción hasta certificación. T176/T177 y el
fence de `default` no protegen por sí solos escritores MySQL.

### Operación durable de maestros

Para Proveedores, Locales y Departamentos se selecciona un registro técnico de
operaciones dentro de `BASE_TAREAS`. La fila de operación y la mutación del
maestro comparten conexión, locks y límite transaccional InnoDB. El registro
debe detectar UUID repetido con payload diferente, devolver el resultado
confirmado ante replay y distinguir `UNKNOWN` de un rollback confirmado.

Después del commit conocido, el servicio proyecta el evento mediante
`AuditoriaService.log_event_idempotent()`. Un fallo de proyección deja
`audit_status=PENDING` o `ERROR` para reconciliación; no repite la mutación.
Si el commit de `BASE_TAREAS` es incierto, el servicio no responde éxito durable
ni ejecuta una escritura ciega. El registro técnico no es una segunda auditoría
central y no crea atomicidad distribuida.

## Limites de propiedad y transaccion

| Dato/efecto | Propietario/base | Garantia requerida |
|---|---|---|
| Nuevas pantallas/orquestacion de maestros | tareas | Todo nuevo codigo funcional queda en `tareas`; consume solo APIs publicas disponibles |
| Proveedor/Local/Departamento, estado actual | Modelos existentes de proveedores/organizacion, sin modificar | Permanecen fuentes/callers preexistentes hasta transicion autorizada; no habilitar writer paralelo |
| Proveedor/Local/Departamento, objetivo | tareas/rol `BASE_TAREAS` | Fuente única tras corte autorizado; sin modelos duplicados ni FK/JOIN cross-database; DDL SQL versionado |
| Membresia, cambio de JEFE, historial de vigencia y fence | organizacion/default, codigo historico preservado | Cambio e historia juntos; la adaptacion a ID externo no se asume implementada |
| Tareas/participaciones/detalles de regularizacion/UUID | tareas/rol `BASE_TAREAS` | Una transaccion para TODO el lote en la conexion operacional resuelta |
| Auditoria central | auditoria/default u owner configurado | Proyeccion por API publica; no participa ficticiamente del commit remoto |
| Notificacion in-app/email | Infraestructura existente | Solo tras commit confirmado; entrega no atomica con tareas |

Tareas reutiliza su resolver `BASE_TAREAS` ya existente mediante los contratos
publicos SYSTEM; no crea resolvers para `proveedores`/`organizacion` ni importa
helpers privados de esas apps. El rol puede resolver a alias Django o MySQL; no se
asume nombre fijo. Empresa activa sigue siendo filtro de todos los datos
company-scoped; Proveedores permanece global.

No usar FK fisicas ni JOINs entre bases/owners. `empresa_id`, `local_id`,
`departamento_id` y `proveedor_id` son referencias estables validadas por APIs
publicas. La forma de migrar las FK/modelos actuales no esta autorizada ni resuelta;
hasta un corte reconciliado no se habilita un writer nuevo sobre otra fuente.

`AUDITORIA_TAREAS` no se habilita como nueva base por esta fase. Evidencia funcional
de la operacion pertenece a BASE_TAREAS; auditoria transversal sigue su API.

## Confirmacion de lote: orden requerido

1. Validar contexto, firma/huella, UUID, seleccion/motivo y resolver backend sin
   escrituras. Verificar que todas las tablas afectadas son transaccionales y que
   schema/constraints necesarios estan disponibles; fallar cerrado si no.
2. Adquirir la coordinacion organizacional para la Empresa; el fence T177 actual
   reside en `default` y protege solo a escritores que participan. Leer membresias
   en orden estable y validar el Departamento mediante el owner en `BASE_TAREAS`.
   Todo escritor de Departamento o membresia debe seguir el protocolo certificado;
   el fence SQLite no protege por si solo escritores MySQL.
3. Bajo el fence, releer usuario/acceso Empresa, VICMEAS y membresias efectivas de
   actor/reemplazante; comparar revisiones del preview. El origen puede no ser elegible.
4. Abrir UN limite transaccional BASE_TAREAS y adquirir el lock empresarial de
   tareas y tareas/ancestros en orden canonico usando los helpers existentes.
   No mezclar conexiones ni llamar wrappers individuales que abran/cierren otras.
5. Revalidar manifiesto exacto, Empresa, estado, eliminacion/anulacion efectiva,
   rol de origen, ausencia de colisiones del reemplazante y permisos por tarea.
   Si cualquier fila falla, rollback del lote entero.
6. Aplicar todas las mutaciones con primitives en esa misma conexion; conservar
   lecturas e identidad; guardar ledger de responsable cuando corresponda, detalles
   y UUID/resultado confirmado en la misma transaccion.
7. Revalidar condiciones que no estan protegidas por el protocolo antes de commit.
   Confirmar el backend resuelto de tareas; mantener la coordinacion hasta conocer
   el resultado. No asumir que otra conexion `BASE_TAREAS` comparte transaccion.
8. Liberar fence. Solo tras commit conocido, proyectar auditoria y notificaciones.
   Responder resultado confirmado separado del estado de efectos secundarios.

Django usa `transaction.atomic(using=alias)` y callbacks `on_commit(using=alias)`
en el limite externo real. MySQL usa una conexion publica y una transaccion con
`mysql_mutation_transaction`, no un `atomic()` en default.
Si hay un atomic externo que aun puede revertir, no notificar al salir de un
savepoint ni devolver exito durable prematuro.

No basta envolver `reassign_responsible()` varias veces: el adapter MySQL abre una
conexion por comando y notifica inmediatamente despues de su commit individual.
Extraer/reutilizar validaciones y primitives locales sin side effects, conservando
servicios individuales existentes y su comportamiento.

## Cambios de membresia concurrentes entre bases

**Propiedad funcional que se protege**: una membresia no puede cambiar mientras
su elegibilidad protegida se usa para confirmar el lote. Si el cambio se confirma
primero, el lote observa la nueva revision y rechaza el preview obsoleto; si el
lote obtiene exclusion certificada primero, el cambio espera y se aplica despues
del commit del lote. Una recuperacion posterior nunca deshace sustituciones confirmadas.

Propuesta: fila `ControlOrganizacionEmpresa` propia de organizacion en `default`. Evita carreras
cuando no hay ninguna membresia que bloquear, protege altas, bajas, cambios de rol
y Departamento activo, y simplifica un orden unico:

`fence organizacion -> Departamento/membresias -> lock Empresa tareas -> tareas/ancestros -> detalles`.

Ningun flujo integrado puede tomar esos locks en orden inverso. Organizacional
puro toma solo el prefijo; tarea que consume elegibilidad toma el orden completo.
Imports/commands/admin deben entrar por los mismos servicios. SQL externo directo
no queda cubierto: se debe impedir operativamente o declarar backend no certificado.

En PostgreSQL u otro backend con locks efectivos, mantener la transaccion que
posee el fence abierta hasta completar el commit operacional. En SQLite no se
puede asumir que `select_for_update` funciona: adquirir exclusion de escritor
real sobre la fila de coordinacion antes de leer, con espera acotada y prueba
con dos conexiones/procesos. No basta mutex de proceso ni test secuencial.
Si default y BASE_TAREAS comparten conexion fisica, unificar el limite transaccional;
no abrir un segundo escritor que se bloquee a si mismo ni simular dos commits.

**Limite explicito**: esto NO es 2PC ni transaccion distribuida. La caida de la
conexion que mantiene el fence puede liberarlo mientras otro servidor aun procesa
el commit. Una consulta de version justo antes del commit no cierra por si sola
esa ventana. F16-G01 exige demostrar el protocolo bajo los fallos admitidos;
sin garantia suficiente se bloquea la ejecucion masiva en esa topologia.
Un lease con expiracion tampoco demuestra seguridad sin fencing efectivo del
consumidor. No implementar leases/versionado como sustituto silencioso de la
garantia, ni aceptar despues un lote invalido como "consistencia eventual".

T176/T177 son evidencia historica de membresias en `default`; no certifican el
protocolo entre la membresia y los nuevos catalogos MySQL. La revision debe elegir
y certificar un protocolo compatible con los backends
desplegados, o registrar `MISSING_SYSTEM_CAPABILITY` y pedir una tarea externa
acotada. Hasta entonces el diseno de lote esta documentado, no certificado.
No se debilita el todo-o-nada de BASE_TAREAS por esta limitacion.

Usuario activo, vinculos Empresa y Permiso pertenecen a CORE: revalidarlos en
confirmacion y antes de commit cumple el chequeo requerido, pero el fence
organizacional no bloquea cambios directos en CORE. No afirmar serializacion
distribuida de permisos que el API publico no ofrece ni modificar CORE para
conseguirla. Una exigencia adicional de revocacion estrictamente simultanea al
commit requiere capacidad/contrato externo; no esta demostrada por la doble lectura.

## Departamento: protocolo sin atomicidad distribuida

La UI/orquestador de tareas solo puede coordinarse con interfaces publicas
existentes. No puede importar modelos/helpers privados de organizacion ni escribir
su estado. Las APIs publicas necesarias para crear/editar/activar Departamentos no
estan disponibles; G19 bloquea estas mutaciones, incluido T201, hasta resolver la
dependencia mediante autorizacion independiente.

1. Preparar operacion con UUID/motivo y revision del Departamento; activo sigue
   siendo verdadero. Preview identifica tareas abiertas, cerradas historicas y
   bloqueos, sin cambiar ninguna.
2. Confirmar bajo fence organizacional y lock empresarial de tareas. Impedir que
   una creacion/asociacion/reactivacion concurrente inserte trabajo abierto en el
   Departamento durante la validacion final: esos writers deben participar del
   protocolo, no solo el endpoint de baja.
3. Las transferencias expresamente seleccionadas a Departamentos activos se
   confirman en BASE_TAREAS con auditoria de antes/despues, sin alterar cerradas
   ni Local/sin ambito ni Empresa/jerarquia. No reutilizar el lote de participantes
   cambiandole el significado del campo rol.
4. Reconsultar todas las tareas abiertas asociadas. Cualquier bloqueo o fila
   nueva impide finalizar; no esconder anuladas del chequeo.
5. Solo con cero bloqueos podria confirmarse `Departamento.activo=False` en la
   fuente autoritativa objetivo `BASE_TAREAS`, manteniendo el control contra
   escritores. Esta operacion no se expone ni ejecuta hasta existir API publica
   autorizada (G19) y evidencia G07; no crear una copia maestra en `default`.

Las transferencias y la baja departamental pueden resolver conexiones/owners
distintos y son commits separados salvo evidencia de una unica conexion transaccional
certificada. Si tareas confirma y falla la actualizacion del maestro, el Departamento
sigue activo y las transferencias confirmadas se conservan; no simular rollback ni
devolver "Departamento desactivado". Registrar/reconciliar la fase pendiente por
UUID, revisar nuevamente antes de finalizar y permitir reintento sin duplicar transferencias.
Esto no rebaja F16-FR20: todo-o-nada aplica a cada lote de tareas, no a una
transaccion distribuida entre la baja y el lote.

Si no es posible impedir nuevos writers en la ventana entre commits, bloquear la
finalizacion (F16-G07). La ausencia de tareas en un preview antiguo no es suficiente.
Reactivacion tambien revalida conflictos organizacionales y referencias historicas,
sin tocar estados/participaciones de tareas.

## Fallos, idempotencia y evidencia

| Punto de fallo | Resultado obligatorio |
|---|---|
| Preview/permiso/membresia invalida | Cero mutaciones y cero notificaciones de exito |
| Primera/intermedia/ultima tarea antes de commit | Rollback de todas las tareas, detalles y ledger nuevo |
| Timeout/deadlock | Error controlado; no retry parcial; nueva validacion completa si se reintenta |
| Commit con respuesta perdida | Resultado INCIERTO al caller; consultar mismo UUID en el mismo backend antes de afirmar exito/fracaso o repetir |
| UUID confirmado, payload identico | Replay sin volver a mutar ni reenviar todo |
| UUID reutilizado con otros datos | Conflicto, nunca sobrescritura |
| Auditoria central fallida postcommit | Lote sigue aplicado, evidencia local intacta, proyeccion pendiente/reconciliable y error sanitizado |
| Email/in-app fallido postcommit | Lote aplicado; logging y estado de entrega diferenciados; no error que invite a repetir el lote |

Un UUID ausente tras error no demuestra rollback si la primera conexion aun puede
confirmar: esperar resolucion del backend/locks y verificar otra vez antes de
autorizar reejecucion. No cambiar backend entre ejecucion y reconciliacion.

No se selecciona todavia un ledger/outbox para los maestros. T216 debe comparar
alternativas de idempotencia, auditoria y reconciliacion, y obtener autorizacion de
owner antes de cualquier modelo/migracion o cambio CORE. No asumir que la API de
auditoria existente haga atomicos los stores. Usar APIs idempotentes existentes
donde el contrato las admite; no crear otra cola global ni infraestructura shadow.
No se promete exactamente-una-vez para email ni atomicidad con filesystem.
