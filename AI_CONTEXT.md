Project Architecture Context
Django Multi-Company Enterprise System

SYSTEM PURPOSE

This project is an enterprise platform built in Django designed to support multiple companies within the same system.

The system manages:

document libraries
project management
user permissions
internal notifications
internal messaging
external database integrations

The system is designed to scale into a full ERP-style platform.

MULTI-COMPANY MODEL

The system uses logical company isolation.

It is NOT multi-tenant by domain or schema.

Instead it uses a company scope stored in the session.

Active company is always stored as:

session['empresa_id']

Every query that accesses company data must respect this scope.

Objects must always be validated against the active company.

Example:

if obj.empresa_id != session['empresa_id']:
access must be denied

ACCESS CONTROL SYSTEM

The project implements a custom permission system instead of Django's default permissions.

Permissions are defined per:

user
company
view

Permission flags include:

ingresar
crear
modificar
eliminar
autorizar
supervisor

Views must use one of these mechanisms:

VerificarPermisoMixin
@verificar_permiso decorator

Each protected view must define:

vista_nombre
permiso_requerido

When access is denied the system must display:

access_control/403_forbidden.html

with the option to request access.

APPLICATION MODULES

access_control

Responsible for:

companies
roles
view permissions
permission assignments
user-company relations

This module defines the core security layer of the system.

biblioteca

Digital document library used to manage legal property documents.

Features:

document upload
document categorization
document access by company
email sharing of document links

notificaciones

Internal notification system.

Features:

system notifications
alerts
user notifications
topbar notification counter
pagination and filtering

settings

User preferences and system configuration.

Features include:

email configuration
theme preferences
dynamic MySQL connection configuration
external database integration

evaluaciones

Module used to manage employee evaluations.

DATA CONNECTION ARCHITECTURE

The system supports dynamic connections to external MySQL databases.

These databases belong to external legacy systems.

Configuration is stored in the model:

SettingsMySQLConnection

Fields include:

nombre_logico
engine
host
port
user
password
db_name
charset
is_active
empresa_id

These connections are used for:

reading data from legacy systems
integration with existing enterprise software

Dynamic connections must never overwrite the main Django database configuration.

They are created dynamically in:

connections.databases[alias]

Connections are used only when required.

External MySQL systems may include very old servers such as:

MySQL 5.1

Because of this the system must support legacy connection modes.

The architecture allows future support for:

PyMySQL legacy driver
external API adapters
data synchronization services

INTERNATIONALIZATION

Templates must include a data-key attribute on visible text.

Example:

<span data-key="settings.mysql_connections.title">Conexiones MySQL</span>

Translation files are located in:

static/lang/en.json
static/lang/sp.json

These files map keys to translations.

Agents must not remove data-key attributes.

FRONTEND STACK

The frontend is intentionally simple.

Templates are server rendered using Django templates.

JavaScript rules:

vanilla JS only
no React
no Vue
no Angular

Bootstrap is used for UI layout and modals.

AJAX interactions use fetch().

DELETION PATTERN

All delete operations follow a strict pattern defined in:

docs/AJAX_DELETION_PATTERN.md

Delete flow:

user clicks delete
modal confirmation appears
AJAX POST request is sent
server returns JSON
UI updates accordingly

RAW exception messages must never be returned.

Instead return structured responses:

success true or false
message_key translation key

SECURITY REQUIREMENTS

Passwords must never appear in logs.

Credentials stored in database must never be returned in API responses.

External database connections must never expose credentials through error messages.

System errors must always be controlled.

TESTING ENVIRONMENT

The project includes a testing configuration:

AppDocs.settings_test

This environment disables optional packages such as:

ckeditor
channels
crispy_forms

Tests should be run using:

python manage.py test --settings=AppDocs.settings_test

DEVELOPMENT PRINCIPLE

The system prioritizes stability over refactoring.

Agents must extend existing patterns instead of replacing them.

Breaking changes must be avoided.

Backward compatibility must be preserved.


For implementation details and reusable task patterns, also refer to:
AI_TASK_PATTERNS.md
COPILOT_PROMPTS.md


END OF CONTEXT