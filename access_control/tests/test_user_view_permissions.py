from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import (
    SIDEBAR_VIEW_NAMES,
    VICMEAS_FIELDS,
    ensure_sidebar_permissions,
    ensure_user_view_permissions,
    get_sidebar_visible_items,
)
from access_control.services.view_catalog import (
    discover_protected_views,
    ensure_protected_views_catalog,
)


class UserViewPermissionsTests(TestCase):
    def setUp(self):
        ensure_protected_views_catalog()
        Vista.objects.get_or_create(nombre="Biblioteca - Propiedades")
        self.user = User.objects.create_user(username="matrix-user")
        self.empresa_a = Empresa.objects.create(codigo="01")
        self.empresa_b = Empresa.objects.create(codigo="02")

    def test_materializes_all_catalogued_views_empty_and_idempotently(self):
        created = ensure_user_view_permissions(self.user, self.empresa_a.id)
        repeated = ensure_user_view_permissions(self.user, self.empresa_a.id)
        protected_names = {
            definition.vista_nombre
            for definition in discover_protected_views()
        }
        permissions = Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa_a,
            vista__nombre__in=protected_names,
        )

        self.assertEqual(created, permissions.count())
        self.assertGreater(created, 0)
        self.assertEqual(repeated, 0)
        for permission in permissions:
            self.assertFalse(any(getattr(permission, field) for field in VICMEAS_FIELDS))

    def test_preserves_existing_flags_and_isolates_company(self):
        vista = Vista.objects.get(nombre="Biblioteca - Propiedades")
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=vista,
            ver=True,
            ingresar=True,
            modificar=True,
        )

        ensure_user_view_permissions(self.user, self.empresa_a.id)
        permission.refresh_from_db()

        self.assertTrue(permission.ver)
        self.assertTrue(permission.ingresar)
        self.assertTrue(permission.modificar)
        self.assertFalse(
            Permiso.objects.filter(usuario=self.user, empresa=self.empresa_b).exists()
        )

    def test_sidebar_uses_ver_only_and_excludes_non_navigable_views(self):
        ensure_user_view_permissions(self.user, self.empresa_a.id)
        self.assertEqual(SIDEBAR_VIEW_NAMES["library_add_owner"], "Biblioteca - Propietarios")
        self.assertEqual(SIDEBAR_VIEW_NAMES["library_list_owners"], "Biblioteca - Propietarios")
        non_navigable = Vista.objects.get(nombre="Biblioteca - Propiedades")
        non_navigable_permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=non_navigable,
        )
        non_navigable_permission.ver = True
        non_navigable_permission.save(update_fields=["ver"])

        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("library_modify_property", visible)
        self.assertEqual(
            Permiso.objects.filter(
                usuario=self.user,
                empresa=self.empresa_a,
                vista__nombre__in=SIDEBAR_VIEW_NAMES.values(),
            ).count(),
            Vista.objects.filter(
                nombre__in=set(SIDEBAR_VIEW_NAMES.values()),
            ).count(),
        )

    def test_legacy_sidebar_wrapper_remains_scoped_and_idempotent(self):
        first = ensure_sidebar_permissions(self.user, self.empresa_a.id)
        second = ensure_sidebar_permissions(self.user, self.empresa_a.id)

        self.assertGreater(first, 0)
        self.assertEqual(second, 0)
        self.assertFalse(
            Permiso.objects.filter(usuario=self.user, empresa=self.empresa_b).exists()
        )