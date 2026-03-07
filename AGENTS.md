Project AI Agent Rules (Version 2)
Applies to: GitHub Copilot, AI assistants, automation agents

GENERAL PRINCIPLE

This repository contains a multi-company enterprise platform built with Django.

AI agents must follow strict architectural, security and stability rules.

Agents must prioritize system stability and must not modify working behaviour unless the user explicitly requests it.

The project is actively used in development and partial production scenarios.
Breaking changes are strictly forbidden.

If an instruction conflicts with the rules defined in this document, the rules in this file take precedence.

This file defines the global rules for AI agents operating inside the repository.

PROJECT ARCHITECTURE

Framework
Django 5.x

Frontend
Server-side templates
Bootstrap UI
Vanilla JavaScript only

Backend structure
Modular Django apps

Database environments
SQLite (development)
PostgreSQL (production)
External MySQL legacy systems via dynamic connections

Deployment
Docker containers in production environments

MULTI-COMPANY SECURITY MODEL

The system is NOT multitenant by domain, schema or database.

Company isolation is implemented logically.

The active company is always stored in the session:

session['empresa_id']

Every request must respect this scope.

Rules:

Never bypass company scoping.

Never trust request parameters for company selection.

Always validate that objects belong to the active company.

Example validation pattern:

if obj.empresa_id != session['empresa_id']:
access must be denied

ACCESS CONTROL SYSTEM

The project implements a custom permission system.

Django default permissions must NOT be used.

Access validation must always be implemented using one of the following:

VerificarPermisoMixin

or

@verificar_permiso decorator

Each protected view must define:

vista_nombre
permiso_requerido

Available permission flags include:

ingresar
crear
modificar
eliminar
autorizar
supervisor

When access fails, the system must use:

access_control/403_forbidden.html

This page allows the user to request access.

Agents must never bypass this permission system.

INTERNATIONALIZATION (I18N)

All visible text inside templates must contain the attribute:

data-key

Example:

<span data-key="settings.mysql_connections.title">Conexiones MySQL</span>

Translation dictionaries are stored in:

static/lang/en.json
static/lang/sp.json

Agents must:

add data-key to any new visible text
never remove existing data-key attributes
report missing translation keys instead of silently editing translation files

DATABASE RULES

The project supports dynamic MySQL connections for legacy systems.

Configuration is stored in the model:

SettingsMySQLConnection

External MySQL systems may include very old versions such as:

MySQL 5.1

Because of this, compatibility layers may be required.

Agents must follow these rules:

Dynamic connections must never overwrite the default Django database configuration.

Dynamic connections must include full connection parameters.

Dynamic aliases must not remain registered after use if the configuration changes.

Credentials must never appear in logs.

Agents must never modify the following infrastructure files unless explicitly requested by the user:

common/utils.py
api/Router_Databases.py

SECURITY RULES

Agents must never:

expose passwords
log credentials
return raw exception messages containing credentials
print sensitive information in logs

Frontend responses must always be controlled responses.

Allowed JSON response structure:

success true or false
message_key translation_key

System exceptions must always be handled and sanitized.

FRONTEND TECHNOLOGY RULES

The frontend stack is intentionally simple.

Allowed technologies:

Django templates
Bootstrap
Vanilla JavaScript

Agents must NOT introduce:

React
Vue
Angular
Alpine
jQuery plugins
new frontend frameworks

AJAX must use the fetch API.

Bootstrap modals must be used for confirmation flows.

Delete operations must follow the project deletion pattern defined in:

docs/AJAX_DELETION_PATTERN.md

PROTECTED CORE FILES

Certain files belong to the base template infrastructure and must NOT be modified by AI agents unless explicitly requested.

These files control layout behaviour, UI initialization and theme configuration.

Protected frontend files include:

static/js/app.js
static/js/layout.js
static/js/theme_config.js
static/js/plugins.js

Rules:

Agents must not modify these files automatically.

If new JavaScript behaviour is required, agents must create a new script file inside the corresponding application static directory.

New scripts must be loaded after the template core scripts.

Agents must never alter template initialization logic.

PROTECTED DJANGO CORE FILES

The following files are considered core infrastructure and must not be modified automatically.

Agents may read them but must not change them unless the user explicitly asks.

Protected files include:

AppDocs/settings.py
AppDocs/settings_test.py
manage.py

Protected infrastructure modules:

common/utils.py
api/Router_Databases.py

Protected base templates may include:

templates/base.html
templates/partials/sidebar.html
templates/partials/topbar.html

These files control global navigation and layout.

Agents must extend functionality without altering base structure whenever possible.

CODE MODIFICATION PRINCIPLES

Agents must follow these rules when modifying code.

Agents must never:

break existing functionality
rewrite working logic without request
introduce large refactors automatically
move files between apps without explicit instruction
change URL names already used in templates

Agents must:

prefer minimal changes
extend existing modules instead of creating parallel logic
maintain backward compatibility
respect the architecture defined in AI_CONTEXT.md and ARCHITECTURE_MAP.md

If a task requires architectural change, the agent must explain the impact before implementing it.

TESTING RULES

The project includes a testing configuration:

AppDocs.settings_test

This environment disables optional packages such as:

ckeditor
channels
crispy_forms

Tests should be executed using:

python manage.py test --settings=AppDocs.settings_test

Agents should add tests when implementing new functionality when possible.

Tests must avoid dependencies on external services unless explicitly configured.

External MySQL connections must be mocked during tests when possible.

FILE ORGANIZATION RULES

Agents must respect the current project structure.

Rules:

Do not move files between apps automatically.

Do not rename apps.

Do not reorganize directory structure.

Prefer extending existing modules rather than creating new parallel modules.

Avoid introducing new dependencies unless explicitly requested.

AI RESPONSE FORMAT RULE

When responding with instructions for implementation:

Agents must respond in plain text only.

No markdown.
No code blocks.
No emojis.

Instructions must be structured clearly so they can be copied in a single action.

AI CONTEXT FILES

Agents must read the following files before generating implementation suggestions:

AI_CONTEXT.md
ARCHITECTURE_MAP.md

These files describe the system architecture and must be used as reference when generating code.

REPOSITORY AI FILES

Agents must always read and respect the following repository files before generating implementation suggestions or code:

AGENTS.md
AI_CONTEXT.md
ARCHITECTURE_MAP.md
AI_TASK_PATTERNS.md
COPILOT_PROMPTS.md

These files define repository rules, architecture, implementation patterns and reusable prompts.

If there is any conflict between these documents, the priority order is:

AGENTS.md
AI_CONTEXT.md
ARCHITECTURE_MAP.md
AI_TASK_PATTERNS.md
COPILOT_PROMPTS.md

END OF AGENT RULES VERSION 2