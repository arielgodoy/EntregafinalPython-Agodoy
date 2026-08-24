Quiero agregar una nueva REGLA CRÍTICA Y PERMANENTE a la documentación de desarrollo ubicada en:

/COPILOT/

ANTES DE MODIFICAR:

1. Lee Paracopilot.md.
2. Revisa todos los archivos existentes dentro de /COPILOT/.
3. Identifica cuál es el documento apropiado para registrar reglas técnicas permanentes del sistema base.
4. NO modifiques código de la aplicación en esta tarea.

NUEVA REGLA OBLIGATORIA

Debe quedar documentado explícitamente que:

static/js/app.js

es un archivo perteneciente al código base/vendor del template y debe considerarse INMUTABLE.

REGLA:

NO MODIFICAR static/js/app.js.

Esto incluye:

- no editar código;
- no parchear funciones;
- no agregar lógica;
- no eliminar lógica;
- no reformatear;
- no minificar nuevamente;
- no cambiar comportamiento interno;
- no utilizarlo como lugar para implementar nuevas funcionalidades.

MOTIVO

app.js contiene lógica base del theme/template y modificarlo puede:

- romper componentes existentes;
- introducir regresiones difíciles de detectar;
- dificultar futuras actualizaciones del template;
- mezclar código propio con código vendor;
- generar comportamientos inesperados en layout, customizer, sidebar, topbar u otros componentes.

ESTRATEGIA OBLIGATORIA

Cuando una funcionalidad parezca requerir modificar app.js, primero debe buscarse una solución mediante código controlado por el proyecto, por ejemplo:

- static/js/theme_config.js;
- un archivo JavaScript propio;
- templates Django;
- context processors;
- views/backend;
- atributos data-* del HTML;
- overrides controlados;
- eventos DOM;
- limpieza/control de localStorage o sessionStorage;
- scripts cargados antes o después del vendor cuando corresponda.

Si app.js intenta sobrescribir una configuración propia del sistema, NO modificar app.js para corregirlo.

Se debe interceptar, neutralizar o reaplicar el comportamiento mediante código propio.

REGLA DE DETENCIÓN

Si Copilot determina que una solicitud NO puede implementarse razonablemente sin modificar:

static/js/app.js

debe DETENERSE.

Debe explicar:

1. qué comportamiento de app.js está interfiriendo;
2. por qué no puede resolverse externamente;
3. qué alternativas existen;
4. qué riesgo tendría modificar app.js.

Debe esperar autorización explícita antes de cualquier intervención.

No debe asumir autorización por el hecho de que el usuario haya solicitado una funcionalidad.

APLICACIÓN ESPECIAL AL THEME

Para preferencias visuales del usuario:

app.js NO debe convertirse en la fuente de verdad.

La arquitectura preferida será:

Base de datos
    ↓
preferencias del usuario
    ↓
Django
    ↓
JSON/configuración renderizada
    ↓
theme_config.js / JS propio
    ↓
atributos data-* del HTML
    ↓
theme/template

localStorage/sessionStorage tampoco deben tener autoridad sobre una preferencia persistida en servidor.

Si app.js utiliza esos mecanismos legacy, la integración debe resolverse externamente sin editar app.js.

IMPORTANTE

Esta regla aplica a TODO desarrollo futuro del proyecto, no solamente al feature actual de ThemePreferences/UserPreferences.

DOCUMENTACIÓN

Agrégala en el archivo apropiado dentro de /COPILOT/.

Si existe un documento de arquitectura, reglas base, restricciones técnicas o equivalente, utilizar ese documento.

Si no existe un lugar claramente apropiado, crea un documento:

/COPILOT/REGLAS_CODIGO_VENDOR.md

con una sección:

## static/js/app.js — ARCHIVO VENDOR INMUTABLE

También agrega una referencia breve desde Paracopilot.md si su estructura está diseñada para apuntar a reglas permanentes.

NO dupliques innecesariamente documentación existente.

ENTREGA

Al terminar indícame:

A. Archivo de /COPILOT/ modificado o creado.
B. Dónde quedó documentada la regla.
C. Si Paracopilot.md fue actualizado.
D. Confirma textualmente:
   "static/js/app.js queda definido como archivo vendor inmutable."
E. Confirma que no modificaste ningún archivo de código de la aplicación.

NO realices todavía ningún cambio al sistema de preferencias del theme.
Esta tarea es exclusivamente documental.