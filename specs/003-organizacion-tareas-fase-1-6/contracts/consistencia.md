# Consistencia, concurrencia y recuperacion

**Estado**: diseno tecnico pendiente de implementacion y certificacion.
No se cambia router, DATABASES ni infrastructure SYSTEM.

## Limites de propiedad y transaccion

| Dato/efecto | Propietario/base | Garantia requerida |
|---|---|---|
| Membresia, cambio de JEFE, historial de vigencia | organizacion/default | Cambio e historia juntos o ninguno |
| Tareas/participaciones/detalles de regularizacion/UUID | tareas/BASE_TAREAS | Una transaccion para TODO el lote |
| Auditoria central | auditoria, backend propio | Proyeccion por API publica; no participa ficticiamente del commit remoto |
| Notificacion in-app/email | Infraestructura existente | Solo tras commit confirmado; entrega no atomica con tareas |

Resolver BASE_TAREAS una vez por operacion, mediante `resolve_operational_backend`,
y conservar identidad/configuracion verificada hasta terminar. No seleccionar
storage por Empresa del request: el rol es GLOBAL POR APP, catalogo MySQL Empresa
codigo 00; Empresa activa sigue siendo filtro de TODOS los datos de negocio.
No confundir Empresa del catalogo de conexiones con Empresa del lote.

`AUDITORIA_TAREAS` no se habilita como nueva base por esta fase. Evidencia funcional
de la operacion pertenece a BASE_TAREAS; auditoria transversal sigue su API.

## Confirmacion de lote: orden requerido

1. Validar contexto, firma/huella, UUID, seleccion/motivo y resolver backend sin
   escrituras. Verificar que todas las tablas afectadas son transaccionales y que
   schema/constraints necesarios estan disponibles; fallar cerrado si no.
2. Adquirir fence de organizacion para la Empresa en `default`; despues obtener
   Departamento/membresias relevantes en orden estable. Todo escritor de membresias
   o `Departamento.activo` debe usar ese mismo fence.
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
7. Revalidar condiciones que no estan protegidas por el fence antes de commit.
   Confirmar BASE_TAREAS; mantener fence de organizacion hasta conocer el resultado.
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
lote toma el fence primero, el cambio espera y se aplica despues del commit del
lote. Una recuperacion posterior nunca deshace sustituciones confirmadas.

Propuesta: fila `ControlOrganizacionEmpresa` propia de organizacion. Evita carreras
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

La revision debe elegir y certificar un protocolo compatible con los backends
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

La UI/orquestador de tareas coordina revision y llama interfaces publicas de
organizacion; organizacion nunca importa tareas.

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
5. Solo con cero bloqueos confirmar baja `Departamento.activo=False` e historia
   en default, manteniendo el control contra escritores hasta esa confirmacion.

Las transferencias y la baja departamental son commits distintos. Si tareas
confirma y default falla, Departamento sigue activo y las transferencias confirmadas
se conservan; no simular rollback ni devolver "Departamento desactivado".
Registrar/reconciliar la fase pendiente por UUID, revisar nuevamente antes de
finalizar y permitir reintento sin duplicar transferencias.
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

Usar APIs centrales idempotentes donde existen (tareas) y claves de evento propias,
sin ampliar su contrato global. Persistir el estado de proyeccion/entrega necesario
en el ledger de dominio solo para reconciliar esta operacion, no crear otra cola
global ni infraestructura shadow.
No se promete exactamente-una-vez para email ni atomicidad con filesystem.
