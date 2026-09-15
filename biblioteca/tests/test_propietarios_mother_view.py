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
from biblioteca.views import VISTA_PROPIETARIOS


class PropietariosMotherViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="propietarios-test")
        self.empresa_activa = Empresa.objects.create(codigo="11", descripcion="Activa")
        self.otra_empresa = Empresa.objects.create(codigo="12", descripcion="Otra")

    def test_active_endpoints_share_mother_view_and_keep_action_permissions(self):
        expected = {
            "crear_propietario": "crear",
            "listar_propietarios": "ingresar",
            "detalle_propietario": "ingresar",
            "eliminar_propietario": "eliminar",
            "modificar_propietario": "modificar",
            "crear_propietario_modal": "crear",
        }
        found = {}

        def collect(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    collect(pattern.url_patterns)
                elif isinstance(pattern, URLPattern) and pattern.name in expected:
                    view_class = pattern.callback.view_class
                    found[pattern.name] = (view_class.vista_nombre, view_class.permiso_requerido)

        collect(get_resolver().url_patterns)
        self.assertEqual(set(found), set(expected))
        self.assertEqual({metadata[0] for metadata in found.values()}, {VISTA_PROPIETARIOS})
        self.assertEqual({name: metadata[1] for name, metadata in found.items()}, expected)

    def test_catalog_and_permissions_are_unique_deny_by_default_and_company_scoped(self):
        _, issues = audit_protected_views()
        self.assertFalse(any(
            issue.issue == "inconsistent_permission"
            and issue.vista_nombre == VISTA_PROPIETARIOS
            for issue in issues
        ))

        ensure_protected_views_catalog()
        definitions = [
            definition
            for definition in discover_protected_views()
            if definition.vista_nombre == VISTA_PROPIETARIOS
        ]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(Vista.objects.filter(nombre=VISTA_PROPIETARIOS).count(), 1)

        created = ensure_user_view_permissions(self.user, self.empresa_activa.id)
        self.assertGreaterEqual(created, 1)
        permiso_activo = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_activa,
            vista__nombre=VISTA_PROPIETARIOS,
        )
        self.assertEqual(
            Permiso.objects.filter(
                usuario=self.user,
                empresa=self.empresa_activa,
                vista__nombre=VISTA_PROPIETARIOS,
            ).count(),
            1,
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
        self.assertFalse(permiso_activo.crear)
        self.assertFalse(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.otra_empresa,
            vista__nombre=VISTA_PROPIETARIOS,
        ).exists())
