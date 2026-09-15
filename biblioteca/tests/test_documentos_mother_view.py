from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import ensure_user_view_permissions
from access_control.services.view_catalog import (
    audit_protected_views,
    discover_protected_views,
    ensure_protected_views_catalog,
)
from biblioteca.views import VISTA_DOCUMENTOS


class DocumentosMotherViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="documentos-test")
        self.empresa_activa = Empresa.objects.create(codigo="41", descripcion="Activa")
        self.otra_empresa = Empresa.objects.create(codigo="42", descripcion="Otra")

    def test_active_endpoints_share_mother_view_and_keep_action_permissions(self):
        expected = {
            "crear_documento": "modificar",
            "eliminar_documento": "eliminar",
            "enviar_enlace_documento": "ingresar",
            "listado_documentos": "ingresar",
        }
        found = []

        def collect(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    collect(pattern.url_patterns)
                elif isinstance(pattern, URLPattern) and pattern.name in expected:
                    callback = pattern.callback
                    view = getattr(callback, "view_class", callback)
                    found.append((pattern.name, view.vista_nombre, view.permiso_requerido))

        collect(get_resolver().url_patterns)
        self.assertEqual({name for name, _, _ in found}, set(expected))
        self.assertEqual({vista_nombre for _, vista_nombre, _ in found}, {VISTA_DOCUMENTOS})
        self.assertEqual({(name, permiso) for name, _, permiso in found}, set(expected.items()))

    def test_catalog_and_permissions_are_unique_deny_by_default_and_company_scoped(self):
        _, issues = audit_protected_views()
        self.assertFalse(any(
            issue.issue == "invalid_permission" and issue.vista_nombre == VISTA_DOCUMENTOS
            for issue in issues
        ))

        ensure_protected_views_catalog()
        definitions = [
            definition
            for definition in discover_protected_views()
            if definition.vista_nombre == VISTA_DOCUMENTOS
        ]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(Vista.objects.filter(nombre=VISTA_DOCUMENTOS).count(), 1)

        ensure_user_view_permissions(self.user, self.empresa_activa.id)
        permiso_activo = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_activa,
            vista__nombre=VISTA_DOCUMENTOS,
        )
        self.assertFalse(any(
            getattr(permiso_activo, field)
            for field in ("ver", "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor")
        ))

        permiso_activo.modificar = True
        permiso_activo.save(update_fields=["modificar"])
        ensure_user_view_permissions(self.user, self.empresa_activa.id)
        permiso_activo.refresh_from_db()
        self.assertTrue(permiso_activo.modificar)
        self.assertFalse(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.otra_empresa,
            vista__nombre=VISTA_DOCUMENTOS,
        ).exists())
