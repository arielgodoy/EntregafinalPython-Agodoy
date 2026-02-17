import unittest
from auditoria.services import AuditoriaService

class DiffSnapshotsTests(unittest.TestCase):
    def test_create_like(self):
        after = {'a': 1, 'b': 2}
        changes = AuditoriaService.diff_snapshots(None, after)
        self.assertEqual(changes['a']['from'], None)
        self.assertEqual(changes['a']['to'], 1)
        self.assertEqual(changes['b']['from'], None)
        self.assertEqual(changes['b']['to'], 2)

    def test_delete_like(self):
        before = {'a': 1, 'b': 2}
        changes = AuditoriaService.diff_snapshots(before, None)
        self.assertEqual(changes['a']['from'], 1)
        self.assertEqual(changes['a']['to'], None)
        self.assertEqual(changes['b']['from'], 2)
        self.assertEqual(changes['b']['to'], None)

    def test_update(self):
        before = {'a': 1, 'b': 2}
        after = {'a': 1, 'b': 3}
        changes = AuditoriaService.diff_snapshots(before, after)
        self.assertNotIn('a', changes)
        self.assertIn('b', changes)
        self.assertEqual(changes['b']['from'], 2)
        self.assertEqual(changes['b']['to'], 3)

if __name__ == '__main__':
    unittest.main()
