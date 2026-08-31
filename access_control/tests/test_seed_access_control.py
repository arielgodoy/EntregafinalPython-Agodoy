import inspect

from django.test import TestCase

from access_control.management.commands import seed_access_control


class SeedAccessControlInvitationViewsTests(TestCase):
    def test_seed_declares_only_canonical_invitation_views(self):
        source = inspect.getsource(seed_access_control.Command.handle)

        self.assertIn("Control de Acceso - Invitaciones", source)
        self.assertIn("Control de Acceso - Invitar Usuario", source)
        self.assertNotIn("'auth_invite'", source)
        self.assertNotIn("'invitaciones'", source)
