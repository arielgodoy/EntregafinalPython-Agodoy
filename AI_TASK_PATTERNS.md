AI Implementation Patterns
Django Multi-Company Enterprise System

This document defines the standard implementation patterns that AI agents must follow when generating or modifying code in this project.

Agents must follow these patterns to ensure consistency with the existing architecture.

If a requested implementation conflicts with these patterns, the agent must follow the architecture rules defined in AGENTS.md.

VIEW CREATION PATTERN

All views that access protected resources must use the access control system.

Views must use one of the following:

VerificarPermisoMixin
or
@verificar_permiso decorator

Class based view example pattern:

class ExampleView(VerificarPermisoMixin, ListView):
vista_nombre = "example_view"
permiso_requerido = "ingresar"

The mixin must be placed before the Django generic view class.

Function based view example pattern:

@verificar_permiso(vista_nombre="example_view", permiso="ingresar")
def example_view(request):
pass

Agents must never bypass this access control system.

COMPANY SCOPE PATTERN

Every query involving company owned data must respect the active company.

The active company is stored in:

request.session['empresa_id']

Example pattern:

empresa_id = request.session.get("empresa_id")

queryset = Model.objects.filter(empresa_id=empresa_id)

Before modifying objects, validation must be performed:

if obj.empresa_id != empresa_id:
return HttpResponseForbidden()

Agents must never trust company identifiers received from request parameters.

MODEL CREATION PATTERN

Models that represent company data must include an empresa field.

Example pattern:

empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="model_items")

Models must not store company identifiers as raw integers.

They must always use ForeignKey relations.

AJAX ENDPOINT PATTERN

AJAX endpoints must always return structured JSON responses.

Allowed JSON structure:

success true or false
message_key translation key

Example success response:

return JsonResponse({"success": True, "message_key": "operation.success"})

Example failure response:

return JsonResponse({"success": False, "message_key": "operation.error"})

Agents must never return raw exception messages.

DELETE OPERATION PATTERN

Delete operations must follow the modal confirmation pattern.

Workflow:

User clicks delete
Confirmation modal appears
User confirms deletion
AJAX POST request is sent
Server validates permission
Server deletes object
Server returns JSON response

Server side pattern example:

if request.method != "POST":
return JsonResponse({"success": False})

try:
obj.delete()
return JsonResponse({"success": True})
except Exception:
return JsonResponse({"success": False, "message_key": "delete.error"})

Agents must not implement delete operations via GET requests.

MYSQL CONNECTION PATTERN

External MySQL connections must be created dynamically.

Configuration source:

SettingsMySQLConnection model.

Fields used:

engine
host
port
user
password
db_name
charset

Connection creation pattern:

connections.databases[alias] = {
"ENGINE": engine,
"NAME": db_name,
"USER": user,
"PASSWORD": password,
"HOST": host,
"PORT": port
}

Agents must ensure the following:

default Django database configuration must never be modified
connections must be removed after use when necessary
credentials must never be logged

MYSQL TEST CONNECTION PATTERN

When testing external connections the following pattern must be used:

open connection
execute safe query
close connection

Example safe query:

SHOW TABLES

Expected response format:

return JsonResponse({
"success": True,
"tables": tables,
"count": len(tables),
"message_key": "settings.mysql_connections.test_success"
})

Error responses must never include raw exceptions.

I18N TEMPLATE PATTERN

Every visible text must include a data-key attribute.

Example:

<button data-key="buttons.save">Guardar</button>

Agents must preserve existing data-key attributes.

Agents must add data-key attributes to new visible text.

Translation files:

static/lang/en.json
static/lang/sp.json

Agents must report missing translation keys.

MODAL UI PATTERN

Bootstrap modals must be used for confirmation dialogs.

Modal workflow:

user action
modal appears
user confirms
AJAX request sent
UI updated dynamically

Agents must avoid page reloads for modal driven actions.

TEST IMPLEMENTATION PATTERN

Tests must be located in:

app_name/tests/

Tests must use the project's testing configuration.

Test command:

python manage.py test --settings=AppDocs.settings_test

Tests must avoid dependencies on external services.

When external connections are required they must be mocked.

CODE CHANGE PRINCIPLE

Agents must follow these development principles:

prefer minimal code changes
respect existing architecture
maintain backward compatibility
avoid unnecessary refactoring
extend existing modules instead of creating parallel logic

If a task requires architectural change, the agent must explicitly state it before implementing.

For reusable task instructions, see:
COPILOT_PROMPTS.md


CODE CHANGE PRINCIPLE:

Additional restriction:

Agents must never modify core template JavaScript files such as:

static/js/app.js
static/js/layout.js
static/js/theme_config.js

These files belong to the template infrastructure.

New functionality must be implemented in separate JS files.




END OF AI TASK PATTERNS