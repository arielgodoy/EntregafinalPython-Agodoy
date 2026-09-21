from django.test import TestCase

from access_control.models import Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas


class TareasAccessUtilityTests(TestCase):
    def test_tasks_scope_resolves_the_five_functional_surfaces(self):
        names = (
            "Tareas",
            "Tareas - Ciclo de vida",
            "Tareas - Hitos",
            "Tareas - Documentos y evidencia",
            "Tareas - Dashboard personal",
        )
        for name in names:
            Vista.objects.create(nombre=name)
        permissions_before = Permiso.objects.count()

        resolution = resolve_scope_vistas("tasks")

        self.assertEqual(resolution.requested_leaf_names, names)
        self.assertEqual(tuple(vista.nombre for vista in resolution.vistas), names)
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), permissions_before)