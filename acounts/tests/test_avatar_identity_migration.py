import importlib

from django.test import SimpleTestCase


migration = importlib.import_module("acounts.migrations.0008_merge_avatar_identity")


class FakeManager:
    def __init__(self, objects):
        self.objects = objects

    def select_related(self, *args):
        return self

    def all(self):
        return list(self.objects)


class FakeApps:
    def __init__(self, avatars):
        self.models = {
            ("acounts", "Avatar"): type("Avatar", (), {"objects": FakeManager(avatars)}),
            ("auth", "User"): type("User", (), {}),
        }

    def get_model(self, app_label, model_name):
        return self.models[(app_label, model_name)]


class FakeUser:
    def __init__(self, **values):
        self.first_name = values.get("first_name", "")
        self.last_name = values.get("last_name", "")
        self.email = values.get("email", "")
        self.saved_fields = []

    def save(self, update_fields=None):
        self.saved_fields.append(tuple(update_fields or ()))


class FakeAvatar:
    def __init__(self, user, **values):
        self.user = user
        self.first_name = values.get("first_name", "")
        self.last_name = values.get("last_name", "")
        self.email = values.get("email", "")


class AvatarIdentityMigrationTests(SimpleTestCase):
    def run_migration(self, *avatars):
        return migration.merge_missing_identity(FakeApps(list(avatars)), schema_editor=None)

    def test_case_a_copies_missing_user_first_name(self):
        user = FakeUser(first_name="")
        self.run_migration(FakeAvatar(user, first_name="Valor"))

        self.assertEqual(user.first_name, "Valor")

    def test_case_b_keeps_existing_user_first_name(self):
        user = FakeUser(first_name="Valor")
        self.run_migration(FakeAvatar(user, first_name=""))

        self.assertEqual(user.first_name, "Valor")
        self.assertEqual(user.saved_fields, [])

    def test_case_c_keeps_equal_first_name_without_change(self):
        user = FakeUser(first_name="Mismo")
        self.run_migration(FakeAvatar(user, first_name="Mismo"))

        self.assertEqual(user.first_name, "Mismo")
        self.assertEqual(user.saved_fields, [])

    def test_case_d_aborts_on_first_name_conflict(self):
        user = FakeUser(first_name="ValorA")

        with self.assertRaisesRegex(RuntimeError, "1 conflictos"):
            self.run_migration(FakeAvatar(user, first_name="ValorB"))

        self.assertEqual(user.first_name, "ValorA")
        self.assertEqual(user.saved_fields, [])

    def test_email_conflict_aborts_without_overwriting_email(self):
        user = FakeUser(email="user@example.test")

        with self.assertRaisesRegex(RuntimeError, "1 conflictos"):
            self.run_migration(FakeAvatar(user, email="avatar@example.test"))

        self.assertEqual(user.email, "user@example.test")
        self.assertEqual(user.saved_fields, [])

    def test_missing_email_is_copied(self):
        user = FakeUser(email="")
        self.run_migration(FakeAvatar(user, email="user@example.test"))

        self.assertEqual(user.email, "user@example.test")