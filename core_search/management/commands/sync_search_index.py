from django.core.management.base import BaseCommand

from access_control.models import Vista
from core_search.models import SearchPageIndex

DEFAULT_ENTRIES = [
    # ===== BIBLIOTECA =====
    (
        "biblioteca.documentos_general",
        "Listado General de Documentos",
        "biblioteca:listado_documentos",
        "search.page.documentos_general",
        "Listado General de Documentos",
        "search.group.biblioteca",
        "documentos doc",
        10,
    ),
    (
        "biblioteca.maestro_documentos",
        "Maestro Documentos",
        "biblioteca:crear_tipo_documento",
        "search.page.maestro_documentos",
        "Maestro Documentos",
        "search.group.biblioteca",
        "documentos maestro",
        11,
    ),
    (
        "biblioteca.maestro_tipos_documentos",
        "Maestro tipos de Documentos",
        "biblioteca:listar_tipos_documentos",
        "search.page.maestro_tipos",
        "Maestro Tipos de Documentos",
        "search.group.biblioteca",
        "tipos documento categorías",
        12,
    ),
    # ===== EVALUACIONES =====
    (
        "evaluaciones.importar_personas",
        "Importar Personas",
        "evaluaciones:importar_personas",
        "search.page.importar_personas",
        "Importar Personas",
        "search.group.evaluaciones",
        "personas importar evaluaciones",
        20,
    ),
    # ===== GESTIÓN DE PROYECTOS =====
    (
        "proyectos.listar",
        "Listar Proyectos",
        "control_de_proyectos:listar_proyectos",
        "search.page.proyectos_listar",
        "Listar Proyectos",
        "search.group.proyectos",
        "proyectos listado",
        30,
    ),
    (
        "proyectos.crear",
        "Crear Proyecto",
        "control_de_proyectos:crear_proyecto",
        "search.page.proyectos_crear",
        "Crear Proyecto",
        "search.group.proyectos",
        "crear proyecto nuevo",
        31,
    ),
    (
        "proyectos.clientes_listar",
        "Listar Clientes",
        "control_de_proyectos:listar_clientes",
        "search.page.clientes_listar",
        "Listar Clientes",
        "search.group.proyectos",
        "clientes listado",
        32,
    ),
    (
        "proyectos.clientes_crear",
        "Crear Cliente",
        "control_de_proyectos:crear_cliente",
        "search.page.clientes_crear",
        "Crear Cliente",
        "search.group.proyectos",
        "crear cliente nuevo",
        33,
    ),
    (
        "proyectos.profesionales_listar",
        "Listar Profesionales",
        "control_de_proyectos:listar_profesionales",
        "search.page.profesionales_listar",
        "Listar Profesionales",
        "search.group.proyectos",
        "profesionales listado",
        34,
    ),
    (
        "proyectos.profesionales_crear",
        "Crear Profesional",
        "control_de_proyectos:crear_profesional",
        "search.page.profesionales_crear",
        "Crear Profesional",
        "search.group.proyectos",
        "crear profesional nuevo",
        35,
    ),
    # ===== CONTROL OPERACIONAL =====
    (
        "operacional.dashboard",
        "Control Operacional Dashboard",
        "control_operacional:dashboard",
        "search.page.operacional_dashboard",
        "Control Operacional Dashboard",
        "search.group.operacional",
        "control operacional dashboard",
        40,
    ),
    # ===== MENSAJERÍA / CHAT =====
    (
        "chat.inbox",
        "chat.inbox",
        "chat_inbox",
        "search.page.chat",
        "Centro de Mensajes",
        "search.group.chat",
        "mensajes chat inbox",
        50,
    ),
    # ===== NOTIFICACIONES =====
    (
        "notificaciones.mis_notificaciones",
        "notificaciones.mis_notificaciones",
        "notificaciones:mis_notificaciones",
        "search.page.notificaciones",
        "Notificaciones",
        "search.group.notificaciones",
        "notificaciones alertas",
        60,
    ),
    (
        "notificaciones.centro_alertas",
        "notificaciones.centro_alertas",
        "notificaciones:centro_alertas",
        "search.page.centro_alertas",
        "Centro de Alertas",
        "search.group.notificaciones",
        "centro alertas notificaciones",
        61,
    ),
    # ===== CONTROL DE ACCESO =====
    (
        "access_control.usuarios",
        "Maestro Usuarios",
        "access_control:usuarios_lista",
        "search.page.usuarios",
        "Gestión de Usuarios",
        "search.group.access_control",
        "usuarios gestión",
        70,
    ),
    (
        "access_control.empresas",
        "Maestro Empresas",
        "access_control:empresas_lista",
        "search.page.empresas",
        "Gestión de Empresas",
        "search.group.access_control",
        "empresas gestión",
        71,
    ),
    (
        "access_control.vistas",
        "Maestro Vistas",
        "access_control:vistas_lista",
        "search.page.vistas",
        "Gestión de Vistas",
        "search.group.access_control",
        "vistas gestión",
        72,
    ),
    (
        "access_control.permisos",
        "Maestro Permisos",
        "access_control:permisos_lista",
        "search.page.permisos",
        "Gestión de Permisos",
        "search.group.access_control",
        "permisos gestión acceso",
        73,
    ),
    # ===== SETTINGS / CONFIGURACIÓN =====
    (
        "settings.empresa_config",
        "company_config",
        "access_control:company_config_list",
        "search.page.empresa_config",
        "Configuración de Empresa",
        "search.group.settings",
        "configuración empresa settings",
        80,
    ),
    (
        "settings.tema",
        "preferencias_tema",
        "access_control:tema_settings",
        "search.page.tema_settings",
        "Preferencias de Tema",
        "search.group.settings",
        "tema preferencias apariencia",
        81,
    ),
    (
        "settings.email_accounts",
        "email_accounts",
        "access_control:email_accounts_list",
        "search.page.email_accounts",
        "Cuentas de Email",
        "search.group.settings",
        "email correo cuentas",
        82,
    ),
]


class Command(BaseCommand):
    help = "Sincroniza SearchPageIndex"

    def handle(self, *args, **options):
        count = 0
        for entry in DEFAULT_ENTRIES:
            key, vista_nombre, url_name, label_key, default_label, group_key, keywords, order = entry

            vista = Vista.objects.filter(nombre=vista_nombre).first()
            if not vista:
                self.stdout.write(
                    self.style.WARNING(
                        f"Vista '{vista_nombre}' no encontrada en BD para entry '{key}'. Saltando."
                    )
                )
                continue

            SearchPageIndex.objects.update_or_create(
                key=key,
                defaults={
                    "vista": vista,
                    "url_name": url_name,
                    "label_key": label_key,
                    "default_label": default_label,
                    "group_key": group_key,
                    "keywords": keywords,
                    "order": order,
                    "is_active": True,
                },
            )
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Search index sincronizado ({count} entries actualizadas)"))
