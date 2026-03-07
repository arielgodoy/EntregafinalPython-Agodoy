System Architecture Map
Django Multi-Company Enterprise Platform

SYSTEM OVERVIEW

This project is a modular enterprise platform built with Django.

The architecture is designed to support:

multi-company management
document management
user access control
internal communication
external system integrations

The platform is structured using independent Django applications that interact through a shared security and company-scoping model.

The core architectural rule is:

All business data is scoped by company using session['empresa_id'].

Every module must respect this rule.

CORE ARCHITECTURE LAYERS

The system is organized into five conceptual layers.

1 Security Layer
2 Company Scope Layer
3 Application Modules
4 Integration Layer
5 Presentation Layer

Each layer must respect the rules of the layers below it.

SECURITY LAYER

This layer controls authentication, authorization, and access validation.

Main module:

access_control

Key components:

Empresa
Proyecto
Rol
UsuarioRol
VistaPermiso
PermisoAsignado
UsuarioEmpresa

Responsibilities:

define companies
assign users to companies
define roles
define permissions per view
validate access rights

View protection mechanisms:

VerificarPermisoMixin
verificar_permiso decorator

Permission flags:

ingresar
crear
modificar
eliminar
autorizar
supervisor

When access is denied the system uses:

access_control/403_forbidden.html

This page allows the user to request access.

COMPANY SCOPE LAYER

This layer ensures that every operation respects the active company.

The active company is stored in:

session['empresa_id']

Rules:

All queries must filter by empresa_id when data is company specific.

Objects must be validated before modification.

Example validation pattern:

if obj.empresa_id != session['empresa_id']:
access must be denied

This rule applies to:

documents
connections
projects
notifications
evaluations

APPLICATION MODULES

Each module implements a specific domain of the system.

Modules must remain independent but respect shared security and company rules.

access_control

Purpose:

security and permissions system.

Responsibilities:

company definitions
user-company relationships
permission assignments
view access validation

All other modules depend on this module.

settings

Purpose:

system configuration and user preferences.

Features include:

email configuration
theme preferences
dynamic MySQL connection management
external system integration settings

Key model:

SettingsMySQLConnection

This model stores connection configurations for legacy systems.

notificaciones

Purpose:

internal notification system.

Features:

system alerts
user notifications
notification center in topbar
pagination and filtering

Notifications may be triggered by:

system events
permission changes
access requests
document events

biblioteca

Purpose:

digital document management system.

Typical use case:

legal property document storage.

Features:

document upload
document categorization
document preview
email sharing of document links

Documents are always associated with a company.

evaluaciones

Purpose:

employee evaluation management.

Features:

evaluation forms
employee performance tracking
integration with external HR data sources

INTEGRATION LAYER

The system integrates with external systems through controlled connectors.

Primary integration type:

external MySQL legacy databases.

Configuration is stored in:

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

Connections are created dynamically using:

connections.databases[alias]

The system must never modify the default Django database connection.

Dynamic connections are used for:

reading legacy ERP data
integrating external payroll systems
reading accounting databases

Legacy databases may include very old MySQL servers.

The architecture allows future connection modes such as:

PyMySQL compatibility driver
remote API adapter
data synchronization pipelines

PRESENTATION LAYER

The user interface is implemented using server-side Django templates.

Frontend technologies:

Django templates
Bootstrap UI framework
Vanilla JavaScript

Rules:

No React
No Vue
No Angular

AJAX calls use fetch().

Modals are implemented using Bootstrap.

DELETION WORKFLOW

Delete operations follow a strict pattern defined in:

docs/AJAX_DELETION_PATTERN.md

Workflow:

User clicks delete
Modal confirmation appears
AJAX POST request is sent
Server validates permissions
Server performs deletion
Server returns JSON response
Frontend updates interface

Server responses must follow the pattern:

success true or false
message_key translation key

Raw exception messages must never be returned.

INTERNATIONALIZATION

The project uses a custom i18n approach based on translation keys.

Visible text must include:

data-key attribute

Example:

<span data-key="settings.mysql_connections.title">Conexiones MySQL</span>

Translations are defined in:

static/lang/en.json
static/lang/sp.json

Agents must maintain data-key attributes.

TESTING ARCHITECTURE

Tests must run using the test settings file:

AppDocs.settings_test

This configuration disables optional dependencies such as:

ckeditor
channels
crispy_forms

Test command:

python manage.py test --settings=AppDocs.settings_test

TEST RULES

Tests should avoid external dependencies.

External database connectors must be mocked when possible.

DEVELOPMENT PRINCIPLES

The system prioritizes stability and backward compatibility.

Agents must follow these principles:

do not break working features
prefer minimal changes
follow existing patterns
avoid unnecessary refactoring
extend existing modules instead of duplicating logic

ARCHITECTURE SUMMARY

Security is handled by access_control.

Company isolation is handled by session['empresa_id'].

Application modules operate within company scope.

External systems are accessed through controlled connectors.

The frontend remains simple and server-rendered.

The architecture allows gradual evolution toward a full enterprise platform.

For implementation rules and coding patterns, refer to:
AGENTS.md
AI_TASK_PATTERNS.md
COPILOT_PROMPTS.md


END OF ARCHITECTURE MAP