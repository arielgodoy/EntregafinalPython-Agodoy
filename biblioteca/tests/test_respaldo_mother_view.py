from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import SIDEBAR_VIEW_NAMES, ensure_user_view_permissions
from access_control.services.view_catalog import (
    audit_protected_views,
    discover_protected_views,
    ensure_protected_views_catalog,
)
from biblioteca.views import VISTA_RESPALDO


class RespaldoMotherViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="respaldo-test")
        self.empresa_activa = Empresa.objects.create(codigo="61", descripcion="Activa")
        self.otra_empresa = Empresa.objects.create(codigo="62", descripcion="Otra")

    def test_backup_endpoint_is_an_independent_mother_view(self):
        found = []

        def collect(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    collect(pattern.url_patterns)
                elif isinstance(pattern, URLPattern) and pattern.name == "respaldo_biblioteca_zip":
                    callback = pattern.callback
                    view = getattr(callback, "view_class", callback)
                    found.append((view.vista_nombre, view.permiso_requerido))

        collect(get_resolver().url_patterns)
        self.assertEqual(found, [(VISTA_RESPALDO, "ingresar")])
        self.assertNotIn(VISTA_RESPALDO, SIDEBAR_VIEW_NAMES.values())

    def test_catalog_and_permissions_are_unique_deny_by_default_and_company_scoped(self):
        _, issues = audit_protected_views()
        self.assertFalse(any(
            issue.issue in {"invalid_permission", "inconsistent_permission"}
            and issue.vista_nombre == VISTA_RESPALDO
            for issue in issues
        ))

        ensure_protected_views_catalog()
        definitions = [
            definition
            for definition in discover_protected_views()
            if definition.vista_nombre == VISTA_RESPALDO
        ]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(Vista.objects.filter(nombre=VISTA_RESPALDO).count(), 1)

        ensure_user_view_permissions(self.user, self.empresa_activa.id)
        permiso_activo = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_activa,
            vista__nombre=VISTA_RESPALDO,
        )
        self.assertFalse(any(
            getattr(permiso_activo, field)
            for field in ("ver", "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor")
        ))

        permiso_activo.ingresar = True
        permiso_activo.save(update_fields=["ingresar"])
        ensure_user_view_permissions(self.user, self.empresa_activa.id)
        permiso_activo.refresh_from_db()
        self.assertTrue(permiso_activo.ingresar)
        self.assertFalse(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.otra_empresa,
            vista__nombre=VISTA_RESPALDO,
        ).exists())
