# GestionDTE — GDTE-B2 Plan técnico de transformación de conexiones

**Estado:** RECONCILIACIÓN DOCUMENTAL ESTÁTICA; pendiente de revisión humana
**Aplicación:** `gestiondte` — `APPLICATION_APP`, según `AppDocs/app_classification.py`
**Alcance escribible de esta reconciliación:** `gestiondte/connection-inventory.md` y este documento únicamente
**Baseline histórico:** 139 IDs congelados, A001–A139
**Inventario reconciliado:** 140 IDs, incluido el sitio post-freeze A140
**Modo:** sin implementación, sin cambios funcionales y sin operaciones de base de datos

> No estamos transformando funcionalidades. Estamos transformando conexiones.

## 1. Objetivo y alcance

Definir una secuencia de trabajo futura para trasladar los accesos del Data Plane de GestionDTE desde el ORM implícito/default a su frontera privada, preservando exactamente el comportamiento observable. Este documento no autoriza implementar ninguno de los lotes.

No se propone cambiar reglas de negocio, contratos públicos, SQL funcional, filtros, orden, paginación, permisos, aislamiento de empresa, HTTP/UX, notificaciones, efectos secundarios, modelos, relaciones, esquema ni datos. No se propone cambiar Settings, SYSTEM/CORE, otras APPLICATION_APPS, `DATABASES`, el router global, `static/js/app.js` ni archivos vendor.

La reconciliación conserva sin cambios los IDs A001-A139 y añade A140 como descubrimiento post-freeze verificado. No se renumeran IDs. La documentación normativa consultada incluye el contrato de transformación operacional, la especificación/checklist/plantilla de auditoría, la arquitectura de aplicaciones, el índice operativo y el estado actual del sistema.

## 2. Arquitectura existente

### 2.1 Ownership y frontera

La clasificación autoritativa procede de `AppDocs/app_classification.py`: `gestiondte` pertenece a `APPLICATION_APPS`; `settings` pertenece a SYSTEM/CORE y es propietario del catálogo físico y de las interfaces públicas de conexión.

La frontera privada de GestionDTE es `gestiondte.services.connection_roles`. Su función es resolver roles lógicos, validar la fuente configurada y entregar metadatos de alias o conexión. El almacenamiento/adaptador ejecuta las operaciones; los servicios conservan lógica de negocio. `DATABASE_ROUTERS` no reemplaza la frontera privada de la aplicación.

Roles observados en el contrato/inventario:

| Rol | Uso observado | Estado relevante para el plan |
|---|---|---|
| `serverbasedte` | Data Plane de certificados y conexión Base DTE | Ya existe y lo consume `CertificadoSIIRepository`; es el rol candidato para el Data Plane de GestionDTE. La fuente física activa de cada entorno no se infiere. |
| `servercontabilidad` | Contabilidad canónica externa y consultas auxiliares | A015–A018 ya fueron transformados en GDTE-B1. No se vuelven a planificar ni modificar. |

`GestionDTEConnectionRole` configura una fuente `DJANGO` o `MYSQL_CONFIG`. GDTE-R001 está cerrada por decisión humana: el router privado y su Control Plane tienen alcance `GLOBAL_PER_APPLICATION`. No se introduce configuración por empresa. Se preservan el aislamiento lógico multiempresa, permisos, filtros, identidades y comportamiento actuales. No se modifica el modelo, esquema, interfaz, autorización ni catálogo físico de Settings.

GDTE-R008 también está cerrada como contrato funcional: se preserva exactamente la visibilidad actual del Admin para A024-A031. Esos accesos continúan pendientes de adaptación de conexión; no se añaden ni eliminan filtros y no se modifican permisos ni Admin.

### 2.2 Resolución y APIs públicas

El resolver diferencia:

- **`DJANGO`:** valida que el alias esté disponible y clasificado como alias SYSTEM permitido; devuelve alias/vendor y el llamador debe usar explícitamente `.using(alias)` o cursor del alias.
- **`MYSQL_CONFIG`:** valida la configuración activa de Settings y la base asociada; el llamador obtiene metadatos y abre por la API pública de Settings.
- **Fail-closed:** rol ausente, alias no permitido/no disponible, configuración ausente/inactiva o nombre de base no válido producen errores explícitos. No se documenta fallback operativo silencioso a `default`.

Interfaces públicas de Settings observadas como consumidoras: `SettingsMySQLConnection`, `open_mysql_connection()`, `get_mysql_connection_config()`/`get_mysql_connection_config_for_request()` y funciones públicas relacionadas con nombres legacy donde aplique. No se copian credenciales, catálogos, selección de conexión ni lógica de apertura. El opener admite los motores MySQL que declara Settings y rechaza motores/API no soportados; no se asume soporte de un backend remoto.

### 2.3 Adaptadores actuales

`CertificadoSIIRepository` es una implementación de referencia local, no una librería común ni un adaptador genérico:

- Para Django alias, ejecuta operaciones de certificados con alias explícito; el borrado usa `transaction.atomic(using=alias)`.
- Para `MYSQL_CONFIG`, usa el opener público de Settings y SQL parametrizado para list/get/insert/update-active/delete, con commit/rollback explícitos en sus operaciones de escritura.
- El almacenamiento PFX es separado del almacenamiento de filas y no existe transacción distribuida.
- No implementa QuerySets, relaciones arbitrarias, búsquedas/annotations genéricas, paginación universal ni las operaciones de RPETC/lectura automática.

`services/rpetc_contabilidad.py` es un adaptador específico de Contabilidad ya tratado en B1. Conserva la diferencia transaccional entre alias Django y driver MySQL; el esquema SQL legacy sigue acoplado y fuera del alcance B2.

### 2.4 Rutas implícitas observadas

Las rutas operacionales de los IDs pendientes emplean managers/modelos Django sin alias explícito. Entre ellas están el importador RPETC, ejecución automática, snapshots, vistas de listado/detalle/revisión/dashboard, ModelAdmin y el fallback de guardado de certificados/formulario. Una selección correcta del rol en otra capa no corrige estas operaciones posteriores si siguen componiéndose con `.objects`/relaciones sobre `default`.

## 3. Baseline histórico y reconciliación post-freeze

El baseline histórico conserva `TOTAL_ACCESS_SITES=139`, IDs A001-A139. GDTE-B1 adaptó A015-A018 a la frontera privada y se da por validado con evidencia previa: tests focalizados 37/37, subconjunto relacional 70/70 y gate físico de conexión de Contabilidad PASS. Esa evidencia no se repite ni extiende a Data Plane en esta planificación. La reconciliación añade A140, por lo que el total actual es 140 y los bypasses operacionales pendientes son 65; las métricas históricas de B1 no cambian.

Los IDs no enumerados como pendientes siguen preservados como referencias históricas. El conjunto de IDs pendientes de este plan es exactamente:

`A010–A014`, `A022–A032`, `A058–A063`, `A066–A080`, `A084–A086`, `A088`, `A090`, `A092`, `A094`, `A097–A098`, `A100–A113`, `A115–A116`, `A118`, `A121`, `A140`.

**A140 confirmado:** `management/commands/ejecutar_lectura_automatica_cesiones.py::Command.handle`, línea 12, ejecuta `LecturaAutomaticaConfig.objects.filter(pk=1).first()` antes de invocar el servicio. Es una lectura productiva, implícita en `default`, de configuración operacional del proceso (no Control Plane de conexiones físicas). Es independiente de A027/A028 (Admin) y A066/A085 (servicio/vista). Se añade como único sitio post-freeze, propiedad `GESTIONDTE_DATA_PLANE`, ruta `IMPLICIT_DEFAULT`, pendiente de adaptación en B2-2.

El total reconciliado es 140 IDs; 65 IDs pendientes corresponden a 63 sitios únicos después de descontar solo A012/A058 y A013/A059. No se cuentan referencias duplicadas como SQL u operaciones físicas adicionales.

Cada fila de la matriz siguiente tiene una clasificación principal única. `ADAPTER` significa `REQUIRES_PRIVATE_ADAPTER_EXTENSION`; `DECISION` significa `REQUIRES_ARCHITECTURAL_DECISION`. Todos los otros estados posibles del esquema de clasificación están definidos en la sección 7. Los riesgos/decisiones transversales no sustituyen ni duplican dicha clasificación.

### Contratos funcionales de referencia

| Código | Contrato que no debe cambiar |
|---|---|
| C-IMP | Importación debe conservar identidad/upsert de tarea, asociación de cesiones, estados/historial, conteos/resultados y atomicidad del conjunto que actualmente está dentro del `atomic()`. |
| C-AUTO | Conservar singleton/configuración, elegibilidad y alcance de empresas, horario, lock/prevención de ejecuciones duplicadas, estados/progreso/resultado y orden de las llamadas externas. El `atomic()` inicial no abarca todo el procesamiento posterior. |
| C-QUERY | Conservar filtros, búsqueda, conteos, agregaciones, orden estable, límites/paginación y forma de respuesta/exportación; no hacer joins físicos entre servidores. |
| C-REVIEW | Conservar unicidad por empresa/cesión, autorización de autor/empresa, texto/estados, relaciones de comentarios, respuestas HTTP/JSON y semántica de create/edit/delete. |
| C-CERT | Conservar `empresa_codigo`, selección/deactivación de certificado activo, snapshots de auditoría, cifrado, resultado del guardado y compensación de archivo actualmente observable. |
| C-ADMIN | Conservar la administración actual de solo lectura y la visibilidad congelada por GDTE-R008; adaptar conexión sin cambiar filtros, permisos ni registros visibles. |
| C-SNAPSHOT | Conservar normalización de estados, valores por defecto, procesamiento por lotes y política de error técnico que preserva el estado válido existente. El caller productivo no está demostrado; mantener `CONTRACT_NOT_PROVEN` y no declarar el servicio muerto. |

## 4. Matriz completa de los 65 IDs pendientes

En todas las filas de Data Plane, `default ORM` es la ruta actual observada. `serverbasedte` es el rol lógico candidato ya existente; el backend real objetivo será el configurado para ese rol (`DJANGO` alias o `MYSQL_CONFIG`) y no se certifica mediante esta lectura estática. Los tests listados son evidencia de cobertura existente, no tests ejecutados en esta tarea.

| ID | Archivo, símbolo y línea actual | Operación / modelo o tabla | Ruta actual → rol/backend objetivo | Clasificación principal | Dependencias y riesgos | Contrato, tests existentes / faltantes, lote |
|---|---|---|---|---|---|---|
| GDTE-A010 | `models.py:151-160`, `CertificadoSII.save` | Guarda certificado y desactiva los demás del mismo `empresa_codigo` | ORM implícito → `serverbasedte`; alias/driver por resolver en configuración | CONTRACT_NOT_PROVEN | El método es público/no productivo según inventario; la vista observada usa repositorio. No eliminar ni alterar el comportamiento sin evidencia de alcance; compañía por código y atomicidad implícita. | C-CERT; `test_certificado_snapshots.py`, `test_certificados_serverbasedte_contracts.py`; falta prueba de `save()` por backend y rollback. B2-6. |
| GDTE-A011 | `services/rpetc_importer.py:200-226`, `importar_resultado_rpetc` | Frontera `transaction.atomic()` del importador | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | La transacción envuelve persistencia compuesta. Multiempresa entra por la tarea; evitar transacción atada a `default`. | C-IMP; `test_rpetc_importer.py`; falta paridad de commit/rollback entre backends. B2-1. |
| GDTE-A012 | `services/rpetc_importer.py:226-234`, `importar_resultado_rpetc` | `update_or_create` de `TareaRPETC` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Clave de tarea y empresa deben preservar identidad/alcance. Es el mismo statement referenciado por A058. | C-IMP; `test_rpetc_importer.py`, `test_rpetc_models.py`; falta prueba de colisión/idempotencia por backend. B2-1. |
| GDTE-A013 | `services/rpetc_importer.py:241-242`, `importar_resultado_rpetc` | Busca `CesionRPETC` por identidad de cesión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | La identidad/constraint de cesión es global; asociación/lectura posterior debe conservar compañía por las tareas relacionadas. Mismo lookup referenciado por A059. | C-IMP; `test_rpetc_importer.py`, `test_rpetc_models.py`; falta prueba de deduplicación y alcance físico. B2-1. |
| GDTE-A014 | `services/rpetc_importer.py:243-283`, `importar_resultado_rpetc` | Inserta/actualiza cesión y enlaza resultado al lote de importación | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Escrituras relacionadas cubiertas por A011; las relaciones task–cession son del Data Plane. | C-IMP; `test_rpetc_importer.py`; falta paridad relacional/rollback en cada backend. B2-1. |
| GDTE-A022 | `services/lectura_automatica.py:197-222`, `ejecutar_lote` | Frontera de transacción para configuración, lock y creación inicial | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | `atomic()` actual es implícito y solo cubre la fase inicial; no ampliarlo ni reducirlo inadvertidamente. | C-AUTO; `test_lectura_automatica.py`; falta transacción por alias/driver y fallo parcial. B2-2. |
| GDTE-A023 | `services/estado_contable_cesiones.py:129-180`, `actualizar_estados_contables_cesiones` | Servicio público de lectura/persistencia de snapshots contables | ORM implícito/default → `serverbasedte` | CONTRACT_NOT_PROVEN | No se encontró caller productivo en GestionDTE; las pruebas llaman directamente al servicio. No declararlo muerto ni inventar un consumidor. | C-SNAPSHOT; `test_estado_contable_cesiones.py`; falta evidencia de reachability/caller y paridad backend. B2-8. |
| GDTE-A024 | `admin.py:27-35`, `CertificadoSIIAdmin` | Changelist/lectura de certificados | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Admin read-only; preservar exactamente la visibilidad actual global aprobada por GDTE-R008. | C-ADMIN; `test_admin.py`; falta backend parity y materialización para Admin. B2-7. |
| GDTE-A025 | `admin.py:37-51`, `TareaRPETCAdmin` | Changelist/relación de tarea y empresa | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Lectura global actual; relación a `Empresa` no debe resolverse con join físico entre bases. GDTE-R008 está cerrado: preservar visibilidad. | C-ADMIN; `test_admin.py`; falta prueba de alias/driver e identidad de Empresa. B2-7. |
| GDTE-A026 | `admin.py:53-66`, `CesionRPETCAdmin` | Changelist de cesiones y campos relacionados | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Cesión sin FK directa de empresa; preservar campos relacionados y visibilidad global actual. | C-ADMIN; `test_admin.py`; falta verificar joins/empresa sin cross-server join. B2-7. |
| GDTE-A027 | `admin.py:68-74`, `LecturaAutomaticaConfigAdmin` | Changelist de configuración singleton | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Es consulta de Admin read-only, no un call site de ejecución automática; preservar singleton y visibilidad actual. | C-ADMIN; `test_admin.py`, `test_lectura_automatica.py`; falta backend parity. B2-7. |
| GDTE-A028 | `admin.py:76-83`, `LecturaAutomaticaEjecucionAdmin` | Changelist de ejecuciones y empresa relacionada | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Es consulta de Admin read-only; ejecución referencia `Empresa`; preservar visibilidad y evitar join entre servidores. | C-ADMIN; `test_admin.py`; falta resolver identidad de Empresa para la lista. B2-7. |
| GDTE-A029 | `admin.py:85-94`, `EstadoContableCesionAdmin` | Changelist de snapshots y relaciones | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Datos company-scoped y referencias canónicas; preservar la visibilidad global vigente, sin nuevos filtros. | C-ADMIN; `test_admin.py`, `test_estado_contable_cesiones.py`; falta backend parity. B2-7. |
| GDTE-A030 | `admin.py:96-104`, `TareaCesionRPETCAdmin` | Changelist de relación tarea–cesión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Compañía indirecta por `TareaRPETC`; no asumir FK física cross-database; preservar visibilidad. | C-ADMIN; `test_admin.py`; falta backend parity. B2-7. |
| GDTE-A031 | `admin.py:106-112`, `CesionRPETCHistorialAdmin` | Changelist de historial con cesión/tarea relacionadas | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Relaciones indirectas; preservar orden y visibilidad global actual. | C-ADMIN; `test_admin.py`; falta backend parity. B2-7. |
| GDTE-A032 | `forms.py:43-59`, `CertificadoUploadForm.save` | Persiste instancia ModelForm si se usa `commit=True` | ORM implícito → `serverbasedte` | CONTRACT_NOT_PROVEN | La vista de carga observada usa `commit=False` y repositorio, pero el método genérico conserva una ruta ORM pública. No declararlo muerto ni cambiar su comportamiento sin evidencia. | C-CERT; `test_certificado_snapshots.py`; falta evidencia de caller productivo y test de `save(commit=True)` por backend. B2-6. |
| GDTE-A058 | `services/rpetc_importer.py:226-234`, `importar_resultado_rpetc` | Referencia duplicada al upsert `TareaRPETC` de A012 | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Solapamiento documental A012/A058: no es SQL ni operación independiente. | C-IMP; mismo coverage de A012; conservar ambos IDs, probar una sola operación. B2-1. |
| GDTE-A059 | `services/rpetc_importer.py:241-242`, `importar_resultado_rpetc` | Referencia duplicada al lookup `CesionRPETC` de A013 | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Solapamiento documental A013/A059: no es SQL ni operación independiente. | C-IMP; mismo coverage de A013; conservar ambos IDs, probar una sola operación. B2-1. |
| GDTE-A060 | `services/rpetc_importer.py:243-267`, `importar_resultado_rpetc` | Inserta nueva `CesionRPETC` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Crear con identidad/valores actuales; el vínculo a tarea es una operación relacionada. | C-IMP; `test_rpetc_importer.py`; falta insert/rollback de MySQL_CONFIG y alias. B2-1. |
| GDTE-A061 | `services/rpetc_importer.py:243-267`, `importar_resultado_rpetc` | Actualiza `CesionRPETC` ya existente | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar campos que el upsert actual actualiza y los que conserva. | C-IMP; `test_rpetc_importer.py`; falta update parity/rollback. B2-1. |
| GDTE-A062 | `services/rpetc_importer.py:245-269`, `importar_resultado_rpetc` | Inserta historial de estados de cesión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Historial y cesión deben compartir la transacción actual. | C-IMP; `test_rpetc_importer.py`; falta orden/historial y rollback por backend. B2-1. |
| GDTE-A063 | `services/rpetc_importer.py:276-283`, `importar_resultado_rpetc` | Obtiene/crea vínculo `TareaCesionRPETC` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar unicidad e identidad task–cession; company scope llega vía tarea. | C-IMP; `test_rpetc_importer.py`, `test_rpetc_models.py`; falta vínculo de IDs físicos y rollback. B2-1. |
| GDTE-A066 | `services/lectura_automatica.py:198-222`, `ejecutar_lote` | Obtiene/crea `LecturaAutomaticaConfig` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | PK singleton 1; su alcance global/configuracional se conserva. | C-AUTO; `test_lectura_automatica.py`; falta configuración en cada backend. B2-2. |
| GDTE-A067 | `services/lectura_automatica.py:198-222`, `ejecutar_lote` | `select_for_update` del registro de configuración | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Lock debe funcionar con backend configurado y conservar exclusión/concurrencia; no degradar a no-op sin prueba. | C-AUTO; `test_lectura_automatica.py`; falta concurrencia/lock real por backend. B2-2. |
| GDTE-A068 | `services/lectura_automatica.py:198-222`, `ejecutar_lote` | Comprueba ejecuciones pendientes/en curso | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Impide lotes duplicados; preservar criterio y ventana actual. | C-AUTO; `test_lectura_automatica.py`; falta interleaving/concurrency parity. B2-2. |
| GDTE-A069 | `services/lectura_automatica.py:198-222`, `ejecutar_lote` | Crea filas `LecturaAutomaticaEjecucion` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Referencia a Empresa debe transportarse lógicamente sin join/FK física entre servidores. | C-AUTO; `test_lectura_automatica.py`; falta persistencia/referencia Empresa en backend real. B2-2. |
| GDTE-A070 | `services/lectura_automatica.py:223-259`, `ejecutar_lote` | Actualiza estado/progreso/resultado de ejecución | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Ocurre después del `atomic()` inicial; no extender transacción ni alterar estados ante errores. | C-AUTO; `test_lectura_automatica.py`; falta fallo parcial y secuencia de estados por backend. B2-2. |
| GDTE-A071 | `services/lectura_automatica.py:223-259`, `ejecutar_lote` | Actualiza siguiente/última ejecución de configuración | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Escritura posterior fuera de la transacción inicial. | C-AUTO; `test_lectura_automatica.py`; falta persistencia tras éxito/fallo y estado final. B2-2. |
| GDTE-A072 | `services/lectura_automatica.py:247-259`, `estado_lote` | Lee ejecuciones ordenadas con `select_related('empresa')` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Referencia a `Empresa` SYSTEM/CORE; materializar identidad por ID/DTO, no asumir join físico. | C-AUTO; `test_lectura_automatica.py`; falta prueba cuando Empresa y Data Plane están en bases distintas. B2-2. |
| GDTE-A073 | `services/estado_contable_cesiones.py:129-180`, `_persistir` | `bulk_create` de `EstadoContableCesion` | ORM implícito/default → `serverbasedte` | CONTRACT_NOT_PROVEN | Servicio público sin caller productivo localizado; no declarar muerto ni atribuir efectos no observados. Guarda relación Empresa/cesión. | C-SNAPSHOT; `test_estado_contable_cesiones.py`; falta evidencia de reachability/caller y bulk parity. B2-8. |
| GDTE-A074 | `services/estado_contable_cesiones.py:129-180`, `_persistir` | `bulk_update` de snapshots | ORM implícito/default → `serverbasedte` | CONTRACT_NOT_PROVEN | Mismo servicio sin caller productivo localizado; bulk update no comparte necesariamente signals/save del ORM. | C-SNAPSHOT; `test_estado_contable_cesiones.py`; falta evidencia de caller y update parity. B2-8. |
| GDTE-A075 | `services/estado_contable_cesiones.py:129-180`, `_persistir` | Lee snapshots existentes para actualizar | ORM implícito/default → `serverbasedte` | CONTRACT_NOT_PROVEN | Snapshot company-scoped, clave empresa/cesión; no se encontró caller productivo. A080 consulta directamente Contabilidad, no este servicio. | C-SNAPSHOT; `test_estado_contable_cesiones.py`; falta evidencia de caller y lectura multi-backend. B2-8. |
| GDTE-A076 | `views.py:70-166`, `_cesiones_rpetc_context` | Consulta cesiones de empresa activa y construye contexto | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Empresa se filtra por `CesionRPETC → TareaCesionRPETC → TareaRPETC`; también obtiene estados contables. | C-QUERY; `test_rpetc.py`, `test_dashboard.py`, `test_exportar_cesiones_excel.py`; falta DTO/filtro backend-neutral. B2-3. |
| GDTE-A077 | `views.py:153-155`, `_cesiones_rpetc_context` | Lee última `TareaRPETC` de empresa | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Orden `-consultada_en`; Empresa ligada por código. | C-QUERY; `test_rpetc.py`, `test_views_sincronizar_rpetc.py`; falta order/list parity. B2-3. |
| GDTE-A078 | `views.py:174-202`, `_rpetc_filtered_queryset` | Filtra cesiones por empresa, RUT, tipo, folio, estado y fechas | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar filtros y joins de empresa/tareas; no debilitar aislamiento. | C-QUERY; `test_revision_cesiones.py`, `test_exportar_cesiones_excel.py`; falta matriz de filtros en ambas fuentes. B2-3. |
| GDTE-A079 | `views.py:205-210`, `_rpetc_annotated_queryset` | `Exists` de comentario/revisión por cesión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Subconsulta sobre tablas de revisión/comentarios; conservar semántica `sin_revisar`. | C-QUERY; `test_revision_cesiones.py`; falta paridad `Exists` y conteos. B2-3. |
| GDTE-A080 | `views.py:213-247`, `_rpetc_apply_payment_filters` / helper | Lee estados contables en lotes, calcula IDs pendientes y filtra cesiones | ORM default para cesiones + `rpetc_contabilidad` B1 | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar intersección de filtros factoring/proveedor, claves faltantes y chunks. El call site invoca `obtener_estados_contables_cesiones`; no invoca el servicio de snapshots A023/A073-A075. | C-QUERY; `test_rpetc_contabilidad.py:329-331`, `test_revision_cesiones.py:173-224`, `test_exportar_cesiones_excel.py:130-145`; falta backend parity de extremo a extremo. B2-3; dependencia B1. |
| GDTE-A084 | `views.py:390-427`, `_lectura_automatica_filas` | Lee ejecuciones con `select_related('empresa')`, filtro y orden | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Relación a Empresa y campos mostrados por UI. Usar identidad/DTO; no cross-server join. | C-AUTO; `test_lectura_automatica.py`; falta prueba de materialización y orden al separar bases. B2-2. |
| GDTE-A085 | `views.py:421-447`, `lectura_automatica_cesiones` | `get_or_create(pk=1)` de configuración y lectura de rango/empresas | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Config singleton; la identidad/consulta de Empresa sigue perteneciendo a SYSTEM/CORE. | C-AUTO; `test_lectura_automatica.py`; falta config/Data Plane y SYSTEM identity parity. B2-2. |
| GDTE-A086 | `views.py:449-545`, `ejecutar_lectura_automatica_cesiones` | Lee/modifica y guarda configuración desde POST | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Mantener validación, permiso, next-run y respuesta HTTP; no cambiar flujo POST. | C-AUTO; `test_lectura_automatica.py`; falta prueba de writes por ambos backends. B2-2. |
| GDTE-A140 | `management/commands/ejecutar_lectura_automatica_cesiones.py:12`, `Command.handle` | Lee `LecturaAutomaticaConfig` singleton por `pk=1` antes de evaluar habilitación/fecha | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Sitio post-freeze independiente de A027/A028 y A066/A085; configuración operacional del proceso, no Control Plane de conexiones. Preservar el flujo global de ejecución y su comportamiento. | C-AUTO; `test_lectura_automatica.py`; falta test del comando, alias/MYSQL_CONFIG, fail-on-default y prueba de backend. B2-2. |
| GDTE-A088 | `views.py:465-567`, `cesiones_data` | Filtra, busca, agrega, ordena y pagina cesiones DataTables | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Company/task joins, dos conteos, monto agregado, búsqueda, `draw/start/length`, límite, desempate PK y estado de pagos. | C-QUERY; `test_revision_cesiones.py`, `test_views_sincronizar_rpetc.py`; falta comparación completa JSON/paginación backend. B2-3. |
| GDTE-A090 | `views.py:588-668`, `exportar_cesiones_excel` | Consulta todas las cesiones filtradas/ordenadas y genera workbook | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Filtros compartidos, pago/revisión, orden `-fecha_cesion, pk`; no truncar a página. | C-QUERY; `test_exportar_cesiones_excel.py`; falta contenido/orden/filtros exactos en cada backend. B2-3. |
| GDTE-A092 | `views.py:669-718`, `detalle_contable_cesion` | Lee cesión restringida por empresa activa y solicita detalle contable | ORM implícito/default + servicio externo → `serverbasedte` para cesión | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Compañía se resuelve por tareas; Contabilidad sigue en `servercontabilidad` (B1), no trasladarla al Data Plane. | C-QUERY; `test_estado_contable_cesiones.py`, `test_revision_cesiones.py`; falta prueba dual-boundary y ausencia de cross-server join. B2-3. |
| GDTE-A094 | `views.py:725-729`, `_revision_cesion` | Obtiene cesión por PK y relación de tarea/empresa activa | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Comprobación de pertenencia a empresa es condición de seguridad, no solo filtro de UI. | C-REVIEW; `test_revision_cesiones.py:95-142`; falta aislamiento multiempresa físico. B2-4. |
| GDTE-A097 | `views.py:773-793`, `revision_cesion` | Lee revisión por empresa/cesión y precarga comentarios/autor | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Revisión única por `(empresa, cesion)`; `User` es referencia SYSTEM/CORE, no moverlo. | C-REVIEW; `test_revision_cesiones.py:62-142`; falta serialización con User externo al backend. B2-4. |
| GDTE-A098 | `views.py:741-769`, `_revision_json` | Itera comentarios relacionados y serializa autor | RelatedManager implícito/default → `serverbasedte` + identidad User | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Evitar N+1/cross-database join; devolver el mismo username/null permitido por contrato actual. | C-REVIEW; `test_revision_cesiones.py:62-142`; falta DTO y error/ausencia de usuario en otro backend. B2-4. |
| GDTE-A100 | `views.py:795-805`, `_revision_con_permisos` | Lee cesión/revisión antes de mutación | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Mantener scoping y permiso ICMEAS existente; no trasladar autorización al repositorio. | C-REVIEW; `test_revision_cesiones.py:62-142`; falta paridad y acceso cruzado denegado. B2-4. |
| GDTE-A101 | `views.py:808-829`, `crear_comentario_revision` | Obtiene/crea revisión por empresa y crea comentario | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Operación compuesta actualmente sin transacción explícita en la vista; conservar comportamiento, no prometer atomicidad nueva. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta escenario de error entre revisión/comentario en ambos backends. B2-4. |
| GDTE-A102 | `views.py:820-825`, `crear_comentario_revision` | Inserta `RevisionCesionComentario` con usuario | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | La FK a User se conserva como identidad externa y se hidrata para serializar. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta create/backend parity y autor externo. B2-4. |
| GDTE-A103 | `views.py:831-845`, `_comentario_autorizado` | Lee comentario con filtros de revisión, empresa, cesión y autor | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Restricciones de dueño/empresa son de seguridad y deben aplicarse antes de devolver contenido. | C-REVIEW; `test_revision_cesiones.py:102-127`; falta caso de otra empresa/otro autor por backend. B2-4. |
| GDTE-A104 | `views.py:847-863`, `editar_comentario_revision` | Actualiza texto y `modificado_en` | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar `update_fields`, instante y autorización de autor. | C-REVIEW; `test_revision_cesiones.py:118-127`; falta update parity y timestamp. B2-4. |
| GDTE-A105 | `views.py:865-880`, `eliminar_comentario_revision` | Elimina comentario autorizado | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Usar la protección existente del endpoint y conservar su respuesta; no modificar UX/modal. | C-REVIEW; `test_revision_cesiones.py:118-127`; falta delete parity/competing delete. B2-4. |
| GDTE-A106 | `views.py:875-877`, `eliminar_comentario_revision` | Comprueba si quedan comentarios | RelatedManager `exists()` implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Determina la eliminación posterior de revisión; respetar orden de operaciones actual. | C-REVIEW; `test_revision_cesiones.py:118-127`; falta exists parity en backend alternativo. B2-4. |
| GDTE-A107 | `views.py:876-879`, `eliminar_comentario_revision` | Elimina revisión sin comentarios restantes | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Cascadas/restricciones existentes deben conservar el resultado; operación no debe exceder empresa/cesión autorizada. | C-REVIEW; `test_revision_cesiones.py:118-127`; falta secuencia de eliminación y rollback. B2-4. |
| GDTE-A108 | `views.py:882-910`, `crear_revision_cesion` | Obtiene/crea revisión company–cession y registra estado/glosa inicial | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar unicidad por empresa/cesión y validaciones/respuesta actuales. | C-REVIEW; `test_revision_cesiones.py:62-101`; falta idempotencia y backend parity. B2-4. |
| GDTE-A109 | `views.py:903-907`, `crear_revision_cesion` | Inserta comentario inicial | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Se ejecuta en la creación; conservar el vínculo a usuario y el texto inicial. | C-REVIEW; `test_revision_cesiones.py:62-101`; falta operación compuesta bajo fallo parcial. B2-4. |
| GDTE-A110 | `views.py:912-931`, `editar_revision_cesion` | Lee revisión de empresa/cesión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Validar company scope antes de modificar. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta lectura por backend y acceso de otra empresa. B2-4. |
| GDTE-A111 | `views.py:926-931`, `editar_revision_cesion` | Guarda cambios de revisión | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Preservar campos/`save()` actual y resultado de respuesta. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta update parity. B2-4. |
| GDTE-A112 | `views.py:933-945`, `eliminar_revision_cesion` | Lee revisión company-scoped antes de borrar | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Comprobar ámbito antes de la cascada. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta lectura/ownership por backend. B2-4. |
| GDTE-A113 | `views.py:940-945`, `eliminar_revision_cesion` | Elimina revisión y sus dependencias configuradas | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | `CASCADE`/relación comentario y cuerpo JSON deben equivaler; no cambiar contrato de eliminación. | C-REVIEW; `test_revision_cesiones.py:62-94`; falta cascade/rollback parity. B2-4. |
| GDTE-A115 | `views.py:1011-1021`, `sincronizar_cesiones_rpetc` | Detecta tarea de sincronización existente por empresa/período | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Evita duplicados/concurrencia; empresa y período son clave de aislamiento. | C-IMP/C-QUERY; `test_views_sincronizar_rpetc.py`; falta concurrencia de tarea ya migrada/backend real. B2-3. |
| GDTE-A116 | `views.py:1050-1058`, `sincronizar_cesiones_rpetc` | Lee cesiones enlazadas a tarea para registro contable | ORM implícito/default → `serverbasedte`; Contabilidad sigue `servercontabilidad` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Cruza dos ownerships por IDs: materializar cesiones localmente, después usar B1 para Contabilidad; no unir bases. | C-IMP; `test_views_sincronizar_rpetc.py`, `test_rpetc_contabilidad.py`; falta prueba dual-backend de Data Plane más B1 mock/contract. B2-3. |
| GDTE-A118 | `views.py:1121-1180`, `_dashboard_resumen` | Agrega cesiones de empresa por período/fecha, conteos/montos/estados/actividad | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Conservar agrupación, límites, filtros temporales y métricas sin joins externos. | C-QUERY; `test_dashboard.py:54-98`; falta igualdad de agregaciones y zona/fecha en cada backend. B2-5. |
| GDTE-A121 | `views.py:1201-1211`, `dashboard_resumen` | Endpoint JSON que delega al resumen filtrado por empresa/período | ORM implícito/default → `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION | Mantener autorización, validación de período, status/shape JSON; vista no elige backend. | C-QUERY; `test_dashboard.py:54-98`; falta comparación HTTP/JSON con backend configurado. B2-5. |

### Acceso post-freeze reconciliado como GDTE-A140

| Referencia | Archivo, símbolo y línea | Operación / modelo | Ruta actual → rol objetivo | Estado de planificación | Evidencia / bloqueo / tests |
|---|---|---|---|---|---|
| `GDTE-A140` (acceso independiente confirmado, posterior al baseline A001-A139) | `management/commands/ejecutar_lectura_automatica_cesiones.py:8-15`, `Command.handle` | `LecturaAutomaticaConfig.objects.filter(pk=1).first()` para decidir si el comando ejecuta la lectura automática | ORM implícito/default → rol privado `serverbasedte` | REQUIRES_PRIVATE_ADAPTER_EXTENSION; incluido en el inventario reconciliado y en B2-2 | Acceso Data Plane/configuración; separado de A027/A028 (Admin) y A085/A066 (vista/servicio). El test `test_lectura_automatica.py` cubre comportamiento del servicio, pero se necesita un test explícito del comando/ruta. B2-2. |

## 5. Solapamientos documentales

- **A012/A058:** la misma instrucción `TareaRPETC.update_or_create`; contar una sola operación física.
- **A013/A059:** el mismo lookup de `CesionRPETC`; contar una sola operación física.
- Los 64 IDs conservan su identidad y tienen clasificación por ID. El conteo de referencias de acceso distintas después de descontar esos dos duplicados documentales es **62**. Las filas A011 y A022 describen límites transaccionales, no sentencias SQL autónomas; tampoco se deben sumar como sentencias.
- Los subpasos A060–A063 y A066–A069 sí distinguen operaciones/efectos diferentes dentro de sus límites compuestos; no se colapsan por estar en el mismo método.

## 6. Matriz de capacidades observadas

La existencia de APIs en el router no implica que exista un ejecutor genérico. La tabla distingue soporte específico ya visible de la capacidad faltante para el Data Plane completo.

| Operación | Implementación/capacidad actual observada | Backends cubiertos por código | Capacidad faltante para B2 | Adaptador privado futuro / contrato de paridad |
|---|---|---|---|---|
| `get` | `CertificadoSIIRepository.get_by_pk_and_empresa`; otros accesos usan ORM implícito | Certificados: Django alias y MySQL config; resto: default ORM | `get` multi-modelo y filtro relacional backend-neutral | Repositorio de la familia; PK, not-found y scope idénticos |
| `filter` | QuerySets en vistas/servicios | ORM del alias implícito; cert tiene filtros propios limitados | Composición general de filtros/relaciones | Storage/query adapter de GestionDTE; mismos predicados |
| `list` | Repo de certificados y QuerySets | Repo: Django/MySQL; resto: default ORM | Lista de modelos Data Plane y DTOs | Adapter por familia; campos y orden iguales |
| `count` | ORM en endpoint DataTables | Default ORM | Count total/filtrado por backend | Query adapter; mismos `recordsTotal`/`recordsFiltered` |
| `exists` | `QuerySet.exists()` en comentario/revisión y filtros | Default ORM | Operación relacional fuera de default | Adapter de revisión; misma verdad booleana y scoping |
| `create` | Certificado repo; ORM en importador, ejecución y vistas | Cert: Django/MySQL; demás: default | Crear registros de tareas, cesiones, comentarios, ejecuciones | Repo por familia; mismos PKs/IDs/valores/errores |
| `update` | Repo certificado update-active; ORM en servicios/views | Cert: Django/MySQL; demás: default | Updates de modelos operacionales fuera de certificado | Repo por familia; preservar `update_fields`, transiciones y side effects |
| `delete` | Repo certificado; ORM comments/revisions | Cert: Django/MySQL; demás: default | Delete/cascade por backend alternativo | Repo de revisión; mismo scope y cascadas |
| `update_or_create` / UPSERT | ORM de tarea importada; sin primitive genérica | Default ORM | Semántica upsert, uniqueness/concurrencia por adapter | Repo importador; identidad y comportamiento de inserción/actualización iguales |
| Bulk operations | `bulk_create`/`bulk_update` en snapshots y bulk migration histórica | Default ORM (migration usa alias de schema editor) | Bulk write productivo contra role configurado | Repo snapshots si se confirma alcance; mantener chunk/tamaño y ausencia/presencia de signals actual |
| `select_for_update` / locks | Configuración singleton en `ejecutar_lote` | ORM default | Lock sobre role backend, garantías reales de motor | Adapter auto; probar motor, contención y prevención de doble ejecución |
| `atomic` / commit / rollback | `atomic()` implícito en importer/auto; cert usa atomic alias en delete y commit/rollback driver; B1 cubre Accounting | Diverso, no unificado | Transacción por alias y por conexión MYSQL_CONFIG para las operaciones compuestas | Adapter específico; preservar límites existentes, no añadir ni quitar atomicidad sin aprobación |
| `on_commit` | No se encontró uso en el código GestionDTE inspeccionado, incluidos services, repositories, utils y tests | Ninguno observado | No existe callback actual cuya semántica deba portarse; si un lote futuro introduce uno, debe ligarse a la transacción resuelta | No aplica hoy; revisar estáticamente si el scope futuro cambia |
| Relaciones por ID | FK/related manager Django; `Empresa`, `User`, task–cession y revision–comment | Default ORM; cert almacena `empresa_codigo` escalar | Materialización de relaciones y consultas sin joins físicos entre bases | DTOs/IDs en storage privado; preservar identidad y ownership lógico |
| Ordenamiento | QuerySets/views con `order_by`, historial y detalle; repo certificados con sus propios resultados | ORM default; SQL específico cert | Orden genérico/consistente no existe en repositorio | Adapter de query; conservar desempate PK y dirección |
| Paginación | DataTables servidor con query ORM y límites | Default ORM | Paginación backend-neutral para `MYSQL_CONFIG` | Query adapter; conservar `draw/start/length`, límite, conteo y page |
| Agregación | `aggregate`/grouping de lista y dashboard en QuerySets | Default ORM | Agregaciones Data Plane sin QuerySet | Adapter de consulta; igualdad exacta de totales/agrupación |
| Serialización | Vistas construyen JSON/Excel desde instancias/QuerySets; revisión serializa relaciones | Default ORM y lógica de vista | Materialización neutral que exponga mismos campos/relaciones | DTO privado más serialización existente; no cambiar shape/HTTP/workbook |
| Documentos / storage | `default_storage` para PFX, lectura y compensación; separada del row store | Storage Django configurado, independiente de alias Data Plane | No es una conexión relacional; coordinación DB/archivo no atómica | Mantener repo/storage; verificar orden y cleanup sin prometer transacción distribuida |
| SQL existente | SQL parametrizado en Certificados, Contabilidad B1 y Base DTE | Cert: Django/MySQL; Accounting/Base DTE: Settings opener para usos soportados | No existe ejecutor SQL genérico para los 64 ORM sites; no se debe inventar SQL de negocio durante el plan | SQL/app repo privado si el análisis de implementación lo requiere; preservar texto funcional/params |

## 7. Capacidades faltantes

La matriz anterior muestra primitives locales para certificados y Contabilidad, pero no una capa genérica que ejecute las consultas/relaciones compuestas de los 65 IDs pendientes. El vacío demostrado es del adaptador privado de GestionDTE, no del catálogo de conexiones de Settings. Las capacidades requeridas se delimitan por familia en la matriz de lotes.

## 8. Diseño de adaptadores privados

### 8.1 Componentes que sí se reutilizan

1. **Resolver/router privado:** `gestiondte.services.connection_roles` conserva roles y validación; el plan no añade roles ni modifica sus reglas. `serverbasedte` es el candidato existente para tablas operativas.
2. **Catalogación/apertura física:** reutilizar interfaces públicas de Settings. No replicar secretos, alias temporales, parámetros, catálogo ni drivers.
3. **Storage/adapters de GestionDTE:** extender repositorios propios, preferentemente por familia/contrato —importación, lectura automática, consultas/revisiones— en vez de copiar QuerySets o crear un ORM genérico. El adapter ejecuta primitives; no decide estados de negocio.
4. **Servicios:** siguen calculando transición, elegibilidad, filtros de negocio, composición y errores. Sustituyen la persistencia implícita por llamadas explícitas al storage sin variar firmas públicas salvo una autorización separada.
5. **Views/forms/admin:** mantienen permisos, empresa de sesión, HTTP, JSON/DataTables, exportación y UX. No eligen ubicación física.

### 8.2 Principios del contrato de datos del adapter

- Para Django alias, cualquier acceso Data Plane debe enlazarse explícitamente al alias resuelto; atomicidad/locks deben operar en ese alias.
- Para MYSQL_CONFIG, el adapter usa exclusivamente el opener público y sentencias parametrizadas. El soporte custom de Certificados no demuestra paridad de los modelos restantes.
- El adapter materializa IDs/valores/DTOs backend-neutrales. No filtra reglas de dominio al resolver.
- Las relaciones `Empresa`/`User` siguen perteneciendo a SYSTEM/CORE. No se crean joins físicos entre servidores ni se mueven/copían esos datos. Preservar IDs y resolver metadata mediante el owner donde el contrato actual la requiere.
- Mantener los mismos códigos de error/ausencia y superficies controladas; no capturar excepciones de forma que un fallo de configuración parezca éxito.
- No crear cambios de modelo/migración ni SQL funcional nuevo como atajo del plan. La existencia de un esquema compatible y datos de destino es prerequisito operativo separado y no se valida aquí.
- La separación archivo/base sigue siendo no atómica; preservar la compensación ya presente y documentar resultados parciales.

### 8.3 No identificados como faltantes del sistema

En el código inspeccionado no se demostró que sea necesario extender Settings/SYSTEM/CORE: el opener y el catálogo requeridos ya existen para las fuentes declaradas. Por tanto `MISSING_SYSTEM_CAPABILITY=0` en este plan. Si durante una implementación se demuestra que una API pública no permite la operación o identidad canónica requerida, detener ese lote y elevar una solicitud separada `MISSING_SYSTEM_CAPABILITY`; no crear workaround local ni modificar SYSTEM/CORE.

No hay evidencia de necesidad de añadir otro rol al router (`REQUIRES_PRIVATE_ROUTER_EXTENSION=0`). GDTE-R001 ya fija y cierra el scope `GLOBAL_PER_APPLICATION`; no se requiere decisión ni cambio de modelo/esquema para reflejarlo.

## 9. Riesgos transaccionales

- **Importador (A011–A014/A058–A063):** el `atomic()` actual es implícito/default y agrupa operaciones; equivalerlo exige que todas las operaciones usen la misma conexión resuelta y que un fallo no deje tarea, cesión, historial o vínculo parcialmente escritos.
- **Lectura automática (A022/A066–A071):** el lock/configuración/creación inicial están dentro de una transacción; cambios de progreso/estado/config ocurren fuera. Mantener exactamente esos límites y estados ante fallo.
- **Revisiones/comentarios (A101–A113):** hay operaciones compuestas que no se observan dentro de una transacción explícita de vista. No introducir transacciones amplias ni alterar el resultado de fallo sin aprobación funcional.
- **Snapshots (A073–A075):** bulk create/update por defecto y sin transacción propia observada; si se retienen, probar chunking, concurrencia y fallo parcial.
- **Certificados (A010/A032):** el `save` del modelo envuelve actividad ORM; el repositorio de certificado tiene ramas específicas. Archivo y base no forman una transacción distribuida.
- **Callbacks:** no se encontró `transaction.on_commit` en GestionDTE. Si una implementación futura añade callbacks, deben quedar ligados a la transacción del backend resuelto y probarse.
- **Rollback:** cada lote debe demostrar que las escrituras están asociadas al backend resuelto y que el rollback/commit se observa allí. Una respuesta HTTP satisfactoria no basta.

## 10. Riesgos multiempresa

- Todas las consultas productivas de cesiones deben mantener la empresa activa desde sesión y el camino de pertenencia actual `CesionRPETC → TareaCesionRPETC → TareaRPETC → Empresa`.
- `TareaRPETC` relaciona Empresa por `codigo`; ejecuciones/revisiones/snapshots tienen sus relaciones propias. `CesionRPETC` no tiene FK directa a Empresa y conserva unicidad global por identidad; no imponerle unicidad por empresa ni cambiar su propiedad.
- `RevisionCesionRPETC` y `EstadoContableCesion` son company-scoped y admiten relación por (empresa, cesión); conservar sus constraints actuales.
- Certificados identifican empresa por `empresa_codigo` string; el formulario valida mediante maestro canónico. No reemplazar el identificador ni confiar en parámetros del cliente en vez de la sesión.
- Admin está actualmente read-only y con queryset no filtrado por empresa. GDTE-R008 fija preservar exactamente esa visibilidad; no añadir filtros/ocultamiento ni cambiar permisos.
- Lectura automática selecciona empresas de forma global y filtra elegibilidad. No acotarla a la empresa de sesión sin un cambio funcional expresamente aprobado.
- Cada adapter debe incluir pruebas negativas de acceso a registros de otra empresa y conservar permisos ICMEAS existentes en las vistas.

## 11. Riesgos entre bases y ownership

- `Empresa`, `User`, `Vista` y `Permiso` pertenecen a SYSTEM/CORE; no se trasladan ni se copian al Data Plane.
- A072/A084 dereferencian Empresa; A097/A098 dereferencian User a través de comentarios. Eliminar joins físicos y materializar referencias por identidad/DTO si el backend está separado.
- A011/A012, A069, A073–A075 y otras tablas tienen referencias a Empresa. Antes de autorizar cambio de backend, probar cómo se conserva el ID lógico sin depender de una FK/constraint cross-database. El plan no altera schema ni presupone constraints externas.
- A092/A116 combinan lectura operacional con consultas Contabilidad. B1 mantiene `servercontabilidad`; se transportan IDs/resultados entre boundaries, no se hacen joins ni se relocaliza Contabilidad.
- A080 invoca un helper de estados contables y realiza filtrado en memoria por PK; la semántica factoring/proveedor es intersección cuando ambos filtros están activos. Confirmar el call path del helper de persistencia de snapshot (A073–A075) antes de incluirlo en un lote productivo.
- No hay un Physical Isolation Gate ejecutado para el Data Plane de GestionDTE. El gate B1 de `servercontabilidad` no prueba que las tablas operativas estén correctamente aisladas.

## 12. Contratos funcionales congelados

1. Identidad/PK, unicidad global o por empresa conforme a modelos actuales; no depender de `_state.db`/clase ORM como identidad funcional.
2. Empresa activa, filtros de pertenencia y permiso ICMEAS. No confiar en selección de empresa recibida por request como autoridad.
3. Transiciones/estados de tareas, cessiones, ejecuciones y comentarios; valores default/normalización y errores existentes.
4. Filtros, búsqueda, orden, desempate, conteos, paginación, límites, workbook/JSON y agregaciones.
5. Relaciones tarea–cesión, revisión–comentario, estados por empresa y referencias a Usuario/Empresa por identidad lógica.
6. Operaciones compuestas y límites `atomic`/lock existentes. No añadir ni quitar atomicidad sin evidencia y autorización.
7. Validaciones de formularios, cifrado/snapshots de auditoría, almacenamiento/limpieza de archivos y tratamiento de fallos.
8. URLs, permisos, métodos HTTP, status/body JSON, mensajes/plantillas y comportamiento de administración.
9. Efectos externos RPETC/Contabilidad/SII permanecen en sus respectivos boundaries, sin duplicar llamada ni alterar orden.

## 13. Plan de lotes

Todos los lotes son **propuestas para autorización futura**. Ninguno está implementado. GDTE-R001 y GDTE-R008 están cerradas por decisión humana. Antes de implementar cualquier lote se deben confirmar sus gates de runtime, incluido destino configurado y esquema/datos compatibles sin cambiar contrato o schema.

**PHYSICAL_GATE heredado por cada lote:** solo después de las pruebas aisladas, con entorno no productivo, destino preparado y autorización explícita, ejercitar las operaciones de ese lote contra el backend físico configurado; verificar filas/relaciones persistidas e instrumentar `default` para demostrar que no atiende Data Plane. Si es inseguro/no autorizado, marcar `NOT_RUN` y no certificar el lote. No autoriza DROP/TRUNCATE, reconstruir tablas operativas en `default` ni migrar datos durante esta planificación.

| BATCH_ID | ACCESS_IDS | Objetivo / dependencias | Archivos esperados en una futura tarea autorizada | Operaciones/adaptador requerido | Contratos / transacciones / empresa | Tests, paridad y gate físico | Rollback, bloqueos y aceptación |
|---|---|---|---|---|---|---|---|
| B2-1 RPETC importer | A011–A014, A058–A063 | Mover persistencia compuesta; GDTE-R001 está cerrado global por aplicación; confirmar identidad/tarea | `services/rpetc_importer.py`, adapter/repository nuevo o existente bajo `gestiondte/`, tests de importer | upsert, lookup, create/update, history, link, transacción única | C-IMP; atomicidad actual; compañía ligada a tarea | `test_rpetc_importer.py`, modelos; tests fail-on-default, rollback, duplicate/replay, alias y MYSQL_CONFIG | Sin blocker de decisión humana. Adapter y gates de runtime pendientes; bloquea si todas las escrituras no usan el mismo backend/transacción. |
| B2-2 Lectura automática | A022, A066–A072, A084–A086, A140 | Config singleton, job, lecturas de estado, comando y vista de ejecución; dependencia runtime con B2-1 | `services/lectura_automatica.py`, `views.py`, `management/commands/ejecutar_lectura_automatica_cesiones.py`, adapter y tests | get/create/update, lock, exists/list/order, persistencia de estado/progreso | C-AUTO; conservar límite de atomic; Empresa por ID/DTO | `test_lectura_automatica.py`; agregar test del comando, concurrency/lock, Company references, both sources y no default-query | Revertir aplicación sin limpiar resultados. Acepta scheduling/estados iguales, lock eficaz y ninguna dependencia en default. Bloquea en FKs cross-db no equivalentes y gates runtime pendientes. |
| B2-3 Consultas RPETC/sync | A076–A080, A088, A090, A092, A115–A116 | Contexto, filtros, DataTables, Excel, detalle y sincronización; dependencia runtime con B2-1 por el importador; conserva boundary B1 Contabilidad | `views.py`, adapter/repository de query propio, tests | filter/list/count/exists/order/pagination/aggregation, transferencia de PK a B1 | C-QUERY y C-IMP; no cross-server join, mantener intersección de filtros pago | `test_rpetc.py`, `test_revision_cesiones.py`, `test_exportar_cesiones_excel.py`, `test_views_sincronizar_rpetc.py`, `test_rpetc_contabilidad.py`; fixtures multiempresa y comparación de JSON/workbook | Revertir código/config, preservar datos. Acepta identical filters/count/page/order/export y Company isolation; fail-on-default. B2-8 no es dependencia de A080. |
| B2-4 Revisiones y comentarios | A094, A097–A098, A100–A113 | CRUD/revisión/serialización; depende de contrato ID de User y materialización de relaciones | `views.py`, adapter/repository de revisión, tests | get/get-or-create/create/update/delete/exists y serializer DTO | C-REVIEW; conservar no-atomic actual, company/autor; referencias User por ID | `test_revision_cesiones.py`; paridad CRUD, relaciones, autores, otra empresa/otro autor, respuesta y errores | Rollback de código, no revertir cambios de usuario. Acepta mismos permisos, comentarios/JSON y no join cross-server. Bloquea si User no se puede resolver con contrato disponible. |
| B2-5 Dashboard | A118, A121 | Aislar agregación/read-only; puede reutilizar el adapter de query B2-3, sin depender funcionalmente de ese lote | `views.py`, query adapter si procede, tests | aggregate/group/filter/order | C-QUERY; empresa y período idénticos | `test_dashboard.py`; comparar períodos, estados, montos y JSON en cada backend | Revertir código/config. Acepta idénticas métricas y aislamiento. Reutilización B2-3 opcional. |
| B2-6 Fallbacks Model/Form de certificado | A010, A032 | Mantener `CONTRACT_NOT_PROVEN`; revisar llamadas/contrato sin convertir la falta de caller en decisión humana | `models.py`, `forms.py`, posible adapter/repository y tests, solo dentro de GestionDTE | create/deactivate + persistencia de form por backend | C-CERT; mantener encryption/audit/company/file compensation | `test_certificado_snapshots.py`, `test_certificados_serverbasedte_contracts.py`; direct-save non-default, failure after file save | Revertir código/config; no borrar datos/archivos indiscriminadamente. No alterar la superficie pública sin evidencia. |
| B2-7 Admin read-only | A024–A031 | GDTE-R008 está cerrado: preservar la visibilidad actual; falta adaptar acceso a conexión | `admin.py`, integración privada de lectura y tests; sin SYSTEM | list/read/search/filter/order/relation materialization | C-ADMIN; preservar read-only y visibilidad actual, sin cambiar permisos ni filtros | `test_admin.py`; usar ambos backends, campos relacionados y sensibilidad; no query de Data Plane default | Revertir código/config. El límite de Django Admin/QuerySet con MYSQL_CONFIG es trabajo técnico; no es una decisión de visibilidad pendiente. |
| B2-8 Accounting-state snapshots | A023, A073–A075 | Confirmar reachability/caller del servicio público; mantener `CONTRACT_NOT_PROVEN`, no declararlo muerto | `services/estado_contable_cesiones.py`, adapter/repository propio y tests si se confirma su uso | get/list, bulk create/update, chunking | C-SNAPSHOT; Company+Cesion; comportamiento técnico de preservar estado válido | `test_estado_contable_cesiones.py`; cobertura directa de la función, pero falta caller productivo, backend parity, partial failures y company isolation | Revertir código/config, no limpiar snapshots. Sin decisión humana pendiente; conservar incertidumbre hasta tener evidencia. |

### Dependencias entre lotes

| Origen | Destino | Evidencia estática | Tipo | Tratamiento |
|---|---|---|---|---|
| B2-2 | B2-1 | `services/lectura_automatica.py::sincronizar_empresa_rpetc` llama `importar_resultado_rpetc` | `HARD_RUNTIME_DEPENDENCY` | B2-2 requiere la persistencia adaptada por B2-1 para no mantener el bypass del importador. |
| B2-3 | B2-1 | `views.py::sincronizar_cesiones_rpetc` llama `sincronizar_empresa_rpetc`, que llama `importar_resultado_rpetc` | `HARD_RUNTIME_DEPENDENCY` | Incluir la dependencia en el orden de implementación y pruebas. |
| B2-3 | GDTE-B1 | Los call sites de consulta/sync invocan `obtener_estados_contables_cesiones` y/o la persistencia contable de B1 | `HARD_RUNTIME_DEPENDENCY` | B1 permanece como boundary de Contabilidad; no trasladar ni reabrir su implementación. |
| B2-5 | B2-3 | El dashboard ejecuta agregaciones propias; podría reutilizar primitives de consulta si el adapter futuro las expone | `OPTIONAL_REUSE` | No es dependencia funcional ni condiciona el orden. |

La relación previamente propuesta B2-3 → B2-8 se elimina: no se encontró llamada a
`actualizar_estados_contables_cesiones` desde A080 ni desde los call sites
productivos inspeccionados. A080 consulta el servicio de Contabilidad de B1
directamente; las pruebas de snapshots llaman la función de snapshots sin
demostrar un consumidor productivo.

## 14. Plan de pruebas futuro

No se ejecutan pruebas en la etapa de planificación. Cada lote autorizado debe añadir/usar pruebas focalizadas por contrato y luego la suite GestionDTE relevante.

1. **Baseline:** fijar respuestas, filas/IDs, estados, filtros, orden, páginas, cantidades, archivos y respuestas de error con evidencia actual antes del cambio.
2. **Backend matrix:** para el role configurado cubrir el branch Django alias y MYSQL_CONFIG según los motores efectivamente soportados y seguros. Mocks/doubles prueban lógica sin abrir una conexión real; no sustituyen el gate físico cuando éste sea seguro y esté autorizado.
3. **Fail-closed:** rol ausente/inactivo, alias no clasificado, fuente equivocada, base no permitida y fallo de apertura deben fallar sin usar `default`.
4. **Isolation:** instrumentar conexiones y demostrar que no se ejecuta SQL operativo de GestionDTE en `default`; cubrir solicitudes con empresa A/B, permisos y registros no autorizados.
5. **Operaciones:** CRUD/upsert/bulk, IDs, constraints, nulidad, order, pagination, aggregate, related ID, serialización y operaciones compuestas por familia.
6. **Transactions/concurrency:** rollback por error inducido, commits, locks, llamadas simultáneas y estado parcial conforme a los límites actuales; `on_commit` solo se prueba si se demuestra su uso en el código del lote.
7. **Side effects:** archivo presente/limpieza de fallo en certificados; llamadas RPETC/Contabilidad mockeadas en tests, sin alterar orden/resultados.
8. **Certificación física:** cuando entorno no productivo, datos, ventana y autorización humana lo permitan, comprobar lecturas/escrituras/relaciones en el backend configurado y estado persistido; solo después considerar el Physical Isolation Gate. Nunca reconstruir tablas operativas en `default` para hacer pasar la prueba.
9. Fallos se clasifican `HISTORICAL`, `INTRODUCED` o `INCONCLUSIVE`; para certificar: cero introducidos e inconclusos, `UNKNOWN=0`, `OPERATIONAL_BYPASS=0` y contrato funcional conservado.

## 15. Criterios de certificación final

La planificación no constituye certificación. La futura implementación solo podrá declararse lista cuando se demuestre, dentro de scope autorizado:

- todos los A001–A140 reconciliados y `UNKNOWN=0`;
- Data Plane completo entra por el router privado propio y `OPERATIONAL_BYPASS=0`;
- Settings físico reutilizado, sin credenciales duplicadas y sin router privado de otra app;
- tests de backend/paridad, fail-closed, company/permission, relaciones, transacciones, side effects y errores;
- verificación física y aislamiento cuando sea seguro/autorizado; si no se ejecuta, anotar `NOT_RUN` y no afirmar certificación completa;
- `CAN_MOVE_DATA_PLANE_BY_CONFIGURATION=YES` sin cambios funcionales ni esquema no aprobados;
- diff restringido a `gestiondte/`, sin migraciones/schema/SYSTEM/CORE inesperados; revisión humana de todos los gates.

La carga/copia de datos o provisión física del destino no se realiza en este plan. Se requiere una operación independiente, con inventario/backup, autoridad y prueba de compatibilidad. No se puede cambiar el puntero de configuración a una base vacía y alegar paridad.

## 16. Bloqueos y decisiones humanas

### Decisiones humanas cerradas

| Código | Decisión | Alcance / efecto |
|---|---|---|
| GDTE-R001 | `GLOBAL_PER_APPLICATION` | Router privado y Control Plane globales por aplicación. Multiempresa conserva exactamente el comportamiento existente. No se modifica modelo, esquema, rol, permiso, interfaz ni Settings. |
| GDTE-R008 | `PRESERVE_EXISTING_ADMIN_VISIBILITY` | Mantener la visibilidad actual de A024-A031. No introducir filtros, cambiar permisos ni modificar Admin. Su adaptación de conexión sigue pendiente. |

No quedan decisiones humanas pendientes para los ocho lotes.

### Bloqueos técnicos, evidencia y runtime

| Código | Clasificación | Accesos afectados | Evidencia / gate pendiente |
|---|---|---|---|
| GDTE-B2-D03 | `CONTRACT_NOT_PROVEN` / `CROSS_DATABASE_DEPENDENCY` | A072, A084, A097-A098 y relaciones lógicas Empresa/Cesión/Usuario | Probar hidratación/materialización de identidades sin cross-server join ni tablas SYSTEM copiadas; conservar IDs y ownership. No autoriza cambio de schema. |
| GDTE-B2-D04 | `TECHNICAL_ADAPTER_AND_TRANSACTION_PARITY` | A011-A014/A058-A063, A022/A066-A071, A073-A075 y otros writes | No existe adapter relacional general para ambos backends. Implementar primitives por familia y demostrar lock/commit/rollback en el backend elegido. |
| GDTE-B2-D05 | `RUNTIME_GATE_PENDING` | Accesos operacionales pendientes de cada lote | Verificar fuente efectiva de `serverbasedte`, destino, esquema/datos compatibles y ausencia de SQL operacional en `default`. No ejecutar gates en esta fase. |
| GDTE-B2-D06 | `TECHNICAL_MULTIEMPRESA_PARITY` | A026, A030-A031, A076-A080, A088/A090/A092/A094, A115-A116/A118/A121 | Mantener pertenencia por las relaciones actuales, filtros por empresa y semántica de intersección de pagos. Resolver mediante adapter/DTO y pruebas; no es decisión de scope. |
| GDTE-B2-D07 | `CONTRACT_NOT_PROVEN` | A010, A032 | La vista de carga usa repositorio/`commit=False`; los métodos públicos mantienen rutas ORM. Falta evidencia de caller productivo y paridad de `save()` directo. No eliminarlos ni cambiar comportamiento. |
| GDTE-B2-D08 | `CONTRACT_NOT_PROVEN` | A023, A073-A075 | Pruebas llaman el servicio directamente, pero no se encontró caller productivo. A080 usa `rpetc_contabilidad`, no el servicio de snapshots. No declarar el servicio muerto ni inventar dependencia. |
| GDTE-B2-D09 | `EXTERNAL_SYSTEM_CAPABILITY_BLOCKER` condicional | Solo una futura operación que requiera API pública no disponible | No hay déficit de Settings demostrado ahora (`MISSING_SYSTEM_CAPABILITY=0`). Si aparece evidencia, detener esa familia y solicitar autorización externa; no modificar SYSTEM/CORE. |
| GDTE-B2-D10 | `RESOLVED_INVENTORY_RECONCILIATION` | GDTE-A140 | El comando se confirmó como acceso independiente, se añadió al inventario y al lote B2-2; no queda candidato sin ID. |

### Dependencias entre lotes

| Origen → destino | Tipo | Estado |
|---|---|---|
| B2-2 → B2-1 | `HARD_RUNTIME_DEPENDENCY` | Confirmada: lectura automática llama al importer mediante `sincronizar_empresa_rpetc`. |
| B2-3 → B2-1 | `HARD_RUNTIME_DEPENDENCY` | Confirmada: `sincronizar_cesiones_rpetc` llega a `sincronizar_empresa_rpetc` y al importer. |
| B2-3 → GDTE-B1 | `HARD_RUNTIME_DEPENDENCY` | Confirmada: las consultas/sync usan el boundary de Contabilidad ya transformado; no reabrir B1. |
| B2-5 → B2-3 | `OPTIONAL_REUSE` | El dashboard ejecuta agregaciones propias; podría reutilizar primitives del adapter, pero no depende funcionalmente de B2-3. |

### Gates de runtime (dimensión independiente de clasificación)

```text
RUNTIME_SOURCE_VERIFICATION = PENDING
PHYSICAL_DESTINATION_VERIFICATION = PENDING
PHYSICAL_SCHEMA_COMPATIBILITY = PENDING
PHYSICAL_DATA_COMPATIBILITY = PENDING
TRANSACTION_PARITY = PENDING (lotes con operaciones transaccionales)
FAIL_CLOSED_AND_NO_DEFAULT_FALLBACK = PENDING
DEFAULT_OPERATIONAL_SQL_GUARD = PENDING
PHYSICAL_ISOLATION_GATE = PENDING (solo seguro, no productivo y autorizado)
```

Estos gates no crean ni duplican IDs. Un sitio puede requerir adapter privado
y, de forma independiente, permanecer bloqueado por verificación de runtime.

## 17. Resumen ejecutivo

- El boundary privado de GestionDTE existe, resuelve configuración y falla cerrado; Settings permanece propietario del catálogo físico.
- La implementación de certificados demuestra una ruta dual para un repositorio acotado, no un adaptador genérico para los 65 accesos operacionales pendientes.
- El baseline histórico conserva A001-A139; A140 es el acceso post-freeze confirmado del comando de management. El inventario actual tiene 140 IDs, 65 pendientes y 63 sitios únicos tras reconciliar los dos pares documentales.
- A027-A028 son consultas del Admin y están en B2-7; A140 es lectura operacional del comando y está en B2-2.
- GDTE-R001 (`GLOBAL_PER_APPLICATION`) y GDTE-R008 (preservar visibilidad actual) están cerradas. No quedan decisiones humanas pendientes.
- 59 IDs requieren extensión de adapter privado y seis permanecen `CONTRACT_NOT_PROVEN`; no se inventa contrato ni se declara muerto ningún acceso.
- No se identificó necesidad demostrada de extensión de Settings/router. Quedan pendientes los gates de runtime, adaptación del Admin y evidencia de callers para snapshots/fallbacks.
- No se propone una sola modificación funcional, de esquema o SYSTEM/CORE. B1 permanece intacto.

## 18. Estado final de planificación

```text
GDTE_CONNECTION_PLAN_STATUS = DOCUMENTAL_RECONCILIATION_COMPLETE; RUNTIME_GATES_PENDING
PLAN_IMPLEMENTED = NO
BASELINE_ACCESS_SITES = 139
TOTAL_ACCESS_SITES = 140
NEW_ACCESS_CONFIRMED = YES
NEW_ACCESS_SITES = 1 (GDTE-A140)
NEW_ACCESS_ID = GDTE-A140
PENDING_ACCESS_IDS = 65
PENDING_IDS_CLASSIFIED = 65
UNCLASSIFIED_PENDING_IDS = 0
UNIQUE_PENDING_ACCESS_SITES = 63
ALL_PENDING_IDS_ASSIGNED_TO_BATCH = YES
ALL_BATCH_DEPENDENCIES_VERIFIED = YES (STATIC; runtime gates remain pending)
DOCUMENTAL_OVERLAPS = A012/A058; A013/A059
UNMAPPED_ACCESS_CANDIDATES = 0
NEW_ACCESS_SITES_ZERO_BASELINE_RECONFIRMED = NO

READY_WITH_EXISTING_INFRASTRUCTURE = 0
REQUIRES_PRIVATE_ADAPTER_EXTENSION = 59
REQUIRES_PRIVATE_ROUTER_EXTENSION = 0
MISSING_SYSTEM_CAPABILITY = 0 (no demostrado; condicional si surge evidencia)
REQUIRES_ARCHITECTURAL_DECISION = 0
CONTRACT_NOT_PROVEN = 6 (A010, A032, A023, A073-A075)
REQUIRES_RUNTIME_VERIFICATION = 65 (gate dimension; no classification)
ALREADY_COMPLIANT = 0
NOT_APPLICABLE = 0
GDTE_R001_DECISION = GLOBAL_PER_APPLICATION
GDTE_R001_STATUS = CLOSED
GDTE_R008_FUNCTIONAL_POLICY = PRESERVE_EXISTING_ADMIN_VISIBILITY
GDTE_R008_CONNECTION_ADAPTATION_STATUS = PENDING

PLANNED_BATCH_COUNT = 8
FIRST_RECOMMENDED_BATCH = B2-1 RPETC importer
FIRST_BATCH_HUMAN_DECISION_BLOCKERS = NONE
FIRST_BATCH_TECHNICAL_WORK_PENDING = relational adapter and transaction parity
FIRST_BATCH_RUNTIME_GATES_PENDING = source/destination/schema/data, fail-closed, no-default guard, physical validation

FUNCTIONAL_CONTRACT_CHANGES_PROPOSED = 0
SYSTEM_CORE_CHANGES_PROPOSED = 0
SCHEMA_CHANGES_PROPOSED = 0
FUNCTIONAL_CONTRACT_CHANGES = 0
SYSTEM_CORE_CHANGES = 0
SCHEMA_CHANGES = 0
```

### Registro histórico de ejecución de planificación (anterior a esta reconciliación)

```text
FILES_CREATED_BY_THIS_EXECUTION = gestiondte/connection-transformation-plan.md
FILES_MODIFIED_BY_THIS_EXECUTION = NONE
PREEXISTING_B1_FILES_PRESERVED =
  gestiondte/services/rpetc_contabilidad.py
  gestiondte/tests/test_rpetc_contabilidad.py
  gestiondte/tests/test_views_sincronizar_rpetc.py
  gestiondte/connection-inventory.md

TESTS_EXECUTED = NO
DJANGO_COMMANDS_EXECUTED = NO
MIGRATIONS_EXECUTED = NO
SQL_EXECUTED = NO
PHYSICAL_CONNECTIONS_OPENED = NO
PERSISTENT_DATA_MODIFIED = NO
GIT_STAGE = NO
GIT_COMMIT = NO
GIT_PUSH = NO

READY_FOR_HUMAN_DIAGNOSTIC = YES (inventory reconciliation is explicit)
READY_FOR_IMPLEMENTATION = NO
```

### Registro de reconciliación documental

```text
RECONCILIATION_DATE = 2026-10-08
FILES_MODIFIED_BY_THIS_EXECUTION = gestiondte/connection-inventory.md; gestiondte/connection-transformation-plan.md
PYTHON_FILES_MODIFIED_BY_THIS_EXECUTION = 0
TEST_FILES_MODIFIED_BY_THIS_EXECUTION = 0
MIGRATIONS_CREATED = 0
TESTS_EXECUTED = NO
DJANGO_EXECUTED = NO
SQL_EXECUTED = NO
PHYSICAL_CONNECTIONS_OPENED = NO
PERSISTENT_DATA_MODIFIED = NO
GIT_STAGE = NO
GIT_COMMIT = NO
GIT_PUSH = NO
READY_FOR_HUMAN_REVIEW = YES
READY_FOR_B2_1_IMPLEMENTATION = NO
ALL_IDS_UNIQUE = YES
ALL_PENDING_IDS_CLASSIFIED = YES
ALL_PENDING_IDS_ASSIGNED_TO_BATCH = YES
INVENTORY_PLAN_CONSISTENCY = YES
A027_A028_BATCH_RECONCILED = YES (Admin, B2-7)
GDTE_R008_FUNCTIONAL_POLICY = PRESERVE_EXISTING_ADMIN_VISIBILITY
GDTE_R008_CONNECTION_ADAPTATION_STATUS = PENDING
CERTIFICATES_UNCERTAINTIES = A010, A032 (CONTRACT_NOT_PROVEN; B2-6)
SNAPSHOT_UNCERTAINTIES = A023, A073-A075 (CONTRACT_NOT_PROVEN; B2-8)
BATCH_COUNT = 8
BATCH_DEPENDENCIES_VERIFIED = YES (static call paths classified; no runtime gate executed)
UNPROVEN_DEPENDENCIES_REMAINING = NONE
B2_1_DOCUMENTAL_IDS = A011-A014, A058-A063 (10)
B2_1_UNIQUE_SITES = 8 (after A012/A058 and A013/A059)
B2_1_HUMAN_DECISION_BLOCKERS = NONE
B2_1_TECHNICAL_WORK_PENDING = private relational adapter; same-backend transaction/commit/rollback parity; fail-closed implementation
B2_1_RUNTIME_GATES_PENDING = configured source/destination; physical schema/data compatibility; backend parity; no-default SQL guard; authorized physical verification
B2_1_READY_FOR_IMPLEMENTATION = NO
```

### Estado de implementación y esquema Base DTE

Registro de seguimiento al 2026-10-08. Este apéndice registra el estado
observado; no cambia las decisiones de alcance ni marca ningún lote como
completado.

- `serverbasedte` usa resolución dinámica. El destino de pruebas vigente es la
  base `gestiondte`; no se incorpora un ID de configuración fijo al código.
- La columna `gestiondte_certificadosii.password_encrypted` fue ampliada con
  autorización previa de `BLOB NULL` a `LONGBLOB NULL`.
- El generador de `gestiondte_lecturaautomaticaejecucion.lote_id` deriva el tipo
  de UUID del backend activo. Django 5.1.3 con MariaDB 10.11 espera UUID nativo;
  la tabla física existente conserva `CHAR(32) NOT NULL` y sigue incompatible.
  La reconciliación física de esa tabla permanece pendiente; no se ejecutó DDL
  UUID durante esta fase.
- Última vista previa del esquema: seis tablas compatibles, tres pendientes
  de creación y una incompatible (`gestiondte_lecturaautomaticaejecucion`).
  No se crearon las tres tablas pendientes.
- No modificar el ERP legacy ni sus estructuras.
- Las 18 pruebas aisladas focalizadas pasaron y `manage.py check` pasó con la
  advertencia conocida de CKEditor. El runner completo permanece bloqueado
  antes de ejecutar pruebas por la dependencia histórica inexistente
  `settings.0007_settingsmysqlconnection`, requerida por
  `gestiondte.0008`.
- El conjunto de cambios incluye un adaptador privado de persistencia RPETC y
  pruebas B2-1; esto no declara el lote validado ni completado. Las puertas de
  validación física y la verificación integral del runner permanecen pendientes.
- Las nuevas claves `data-key` de la vista previa Base DTE aún no existen en
  `static/lang/en.json` ni `static/lang/sp.json`; la traducción queda pendiente.
- B2-1 y los demás lotes conservan sus estados de planificación y validación
  previos; este registro no declara completado ningún lote ni autoriza nuevas
  operaciones sobre la base.

```text
UUID_GENERATOR_BACKEND_AWARE = YES
UUID_PHYSICAL_RECONCILIATION = PENDING
BASE_DTE_TABLES_COMPATIBLE = 6
BASE_DTE_TABLES_PENDING = 3
BASE_DTE_TABLES_INCOMPATIBLE = 1
FOCUSED_ISOLATED_TESTS = 18 PASSED
DJANGO_CHECK = PASSED (known CKEditor warning)
FULL_TEST_RUNNER = BLOCKED (missing settings.0007_settingsmysqlconnection)
BASE_DTE_PREVIEW_TRANSLATIONS = PENDING (en.json, sp.json)
LEGACY_MODIFIED = NO
SYSTEM_CORE_MODIFIED = NO
PENDING_BATCHES_MARKED_COMPLETE = NO
```
