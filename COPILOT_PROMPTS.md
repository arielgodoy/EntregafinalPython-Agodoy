Reusable Copilot Prompts
Django Multi-Company Enterprise System

This file contains reusable prompt templates for common implementation tasks in this repository.

Agents must always respect:
AGENTS.md
AI_CONTEXT.md
ARCHITECTURE_MAP.md
AI_TASK_PATTERNS.md

All responses must be generated in plain text only.

GENERAL COPILOT HEADER

Use this header before implementation requests:

INSTRUCCIONES PARA COPILOT (RESPONDER SOLO EN TEXTO PLANO SIMPLE, SIN MARKDOWN, SIN EMOJIS, SIN PREGUNTAS)

ANTES DE EMPEZAR (OBLIGATORIO)
LEE Y RESPETA ESTOS DOCUMENTOS:
AGENTS.md
AI_CONTEXT.md
ARCHITECTURE_MAP.md
AI_TASK_PATTERNS.md
docs/COPILOT_RULES.md
docs/AI_CONTEXT_SYSTEM.md
docs/AI_PROMPT_MASTER.md
docs/AI_DEBUG_PROMPT.md
docs/AI_SECURITY_PROMPT.md
docs/AJAX_DELETION_PATTERN.md

REGLAS CRÍTICAS DEL PROYECTO

NO romper multiempresa: empresa_id SIEMPRE desde session['empresa_id'] (HTTP).

NO usar django permissions estándar.

Usar VerificarPermisoMixin o @verificar_permiso según corresponda.

NO agregar librerías salvo instrucción explícita.

i18n obligatorio: todos los textos visibles deben tener data-key.

NO exponer credenciales ni errores crudos.

Respetar arquitectura existente y cambios mínimos.

PROMPT 1: CREAR CRUD MULTIEMPRESA

OBJETIVO
Crear un CRUD completo server-side para una entidad nueva dentro de una app Django existente, respetando multiempresa, permisos, i18n y patrón de eliminación AJAX.

REQUERIMIENTOS

Modelo asociado a Empresa mediante ForeignKey

List, Create, Update, Delete

Filtrar siempre por session['empresa_id']

Validar pertenencia del objeto a empresa activa

Usar VerificarPermisoMixin

Agregar data-key a todos los textos visibles

Delete con modal + AJAX siguiendo el patrón del proyecto

Entregar al final rutas modificadas, urls nuevas y keys i18n nuevas

PROMPT 2: CREAR ENDPOINT AJAX PROTEGIDO

OBJETIVO
Crear un endpoint AJAX protegido para una acción específica dentro de una app existente.

REQUERIMIENTOS

Proteger con VerificarPermisoMixin o @verificar_permiso

Validar empresa activa desde session['empresa_id']

Validar pertenencia del objeto a la empresa activa

Retornar JsonResponse con:
success true o false
message_key

No devolver excepciones crudas

Si aplica, agregar tests mínimos

Indicar archivos modificados y keys i18n nuevas

PROMPT 3: AGREGAR OPCIÓN AL SIDEBAR

OBJETIVO
Agregar una nueva opción al menú lateral del sistema sin romper la navegación existente.

REQUERIMIENTOS

Ubicar el template real del sidebar

Agregar el item en la sección correcta

Usar {% url %} con el name correcto

Agregar data-key al texto visible

No alterar otros ítems del menú

Confirmar al final archivo modificado y key i18n nueva

PROMPT 4: AGREGAR MODAL BOOTSTRAP CON FETCH

OBJETIVO
Agregar un modal Bootstrap con JavaScript vanilla para ejecutar una acción sobre un registro.

REQUERIMIENTOS

No usar librerías nuevas

Usar fetch

Enviar token CSRF si corresponde

Mostrar respuesta controlada

No usar alert() salvo que el proyecto ya lo haga

Respetar patrón AJAX_DELETION_PATTERN.md si es una eliminación

Agregar data-key a todos los textos visibles

PROMPT 5: CREAR SERVICIO DE NEGOCIO

OBJETIVO
Crear un servicio reutilizable dentro de una app siguiendo el patrón services del proyecto.

REQUERIMIENTOS

Ubicar carpeta services o crearla siguiendo el patrón existente

Crear función pública clara

Mantener lógica fuera de views cuando corresponda

Agregar excepciones propias si hace falta

Agregar tests unitarios

No mover lógica productiva sin instrucción explícita

PROMPT 6: INTEGRAR CONEXIÓN MYSQL DINÁMICA

OBJETIVO
Implementar o extender una integración con conexiones MySQL dinámicas usando SettingsMySQLConnection sin romper el sistema actual.

REQUERIMIENTOS

Usar session['empresa_id'] como fuente de verdad

No modificar common/utils.py ni api/Router_Databases.py salvo instrucción explícita

No sobrescribir alias globales

Crear alias dinámicos seguros y completos

Incluir siempre ENGINE, NAME, USER, PASSWORD, HOST, PORT, OPTIONS, CONN_MAX_AGE, ATOMIC_REQUESTS

No exponer credenciales

Agregar tests o validaciones mínimas

PROMPT 7: AGREGAR TEST DE CONEXIÓN MYSQL

OBJETIVO
Agregar o modificar una prueba de conexión MySQL para una configuración existente.

REQUERIMIENTOS

Ejecutar una consulta segura como SHOW TABLES

Validar empresa activa y pertenencia del registro

Retornar JSON controlado con:
success
tables
count
message_key

No devolver errores crudos

Cerrar la conexión después de usarla

Si el alias ya existe y cambia la configuración, cerrar y reconfigurar antes de consultar

PROMPT 8: CREAR EXPORTACIÓN E IMPORTACIÓN JSON

OBJETIVO
Agregar exportación e importación de configuraciones en formato JSON para registros de una empresa activa.

REQUERIMIENTOS

Exportar sólo datos de la empresa activa

Importar sobreescribiendo registros de la empresa activa dentro de transaction.atomic

Validar formato JSON y duplicados

No permitir afectar otra empresa

Si falta un campo por compatibilidad, aplicar valor por defecto conservador

Agregar botón exportar e importar en la UI con data-key

PROMPT 9: REVISIÓN DE SEGURIDAD DE UNA APP

OBJETIVO
Revisar una app del proyecto para detectar incumplimientos de seguridad, multiempresa y permisos.

REQUERIMIENTOS

Revisar uso de session['empresa_id']

Revisar si las vistas usan VerificarPermisoMixin o @verificar_permiso

Revisar pertenencia de objetos a empresa activa

Revisar i18n data-key

Revisar si hay exposición de errores o credenciales

Entregar reporte en texto plano sin modificar archivos, salvo instrucción explícita

PROMPT 10: REFACTOR CONSERVADOR

OBJETIVO
Realizar un refactor mínimo y seguro sobre una funcionalidad existente sin alterar comportamiento productivo.

REQUERIMIENTOS

Hacer cambios mínimos

Mantener compatibilidad hacia atrás

No cambiar nombres de rutas, vistas o templates si no es necesario

No mover archivos entre apps sin instrucción explícita

Entregar listado exacto de archivos modificados y explicación breve del impacto

PROMPT 11: CREAR VISTA PROTEGIDA POR EMPRESA

OBJETIVO
Crear una vista nueva que opere sobre datos de empresa respetando access_control y company scoping.

REQUERIMIENTOS

Usar VerificarPermisoMixin o @verificar_permiso

vista_nombre y permiso_requerido obligatorios

Validar session['empresa_id']

Filtrar queryset por empresa activa

Si se trabaja con un objeto, validar que pertenece a la empresa activa

Usar render server-side y i18n data-key

PROMPT 12: GENERAR REPORTE PARA CHATGPT

OBJETIVO
Analizar una app o módulo y generar un reporte técnico para ser compartido con ChatGPT o revisión humana.

REQUERIMIENTOS

No modificar archivos

Leer modelos, vistas, urls, templates, services y tests

Explicar arquitectura interna

Explicar dependencias con access_control y empresa activa

Indicar riesgos y próximos pasos

Entregar sólo texto plano

END OF COPILOT PROMPTS