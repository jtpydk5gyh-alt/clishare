import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cshcli.store import Store


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "restore_drill.py"
_spec = importlib.util.spec_from_file_location("restore_drill", SCRIPT)
drill_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drill_module)


class RestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "coordinator.sqlite3"
        self.workdir = self.root / "drill"
        self.store = Store(self.database)
        self.ana = self.store.register_user("ana")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.lease = self.store.acquire_leases(self.ana["id"], self.project["id"],
                                               "agent-1", ["file:src"], ttl=600)[0]
        self.store.put_memory(self.ana["id"], self.project["id"], "k", "v", 0)

    def test_a_backup_is_a_consistent_snapshot(self):
        target = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        self.assertTrue(target.is_file())
        self.assertEqual(drill_module.counts(target)["leases"], 1)
        self.assertEqual(drill_module.counts(target)["projects"], 1)

    def test_a_restore_into_an_empty_database_reproduces_the_state(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        restored = drill_module.restore(snapshot, self.workdir / "new.sqlite3")
        self.assertEqual(restored["counts"]["leases"], 1)
        self.assertEqual(restored["counts"]["users"], 1)
        self.assertEqual(restored["counts"]["memory"], 1)

    def test_the_fence_never_goes_backwards(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        restored = drill_module.restore(snapshot, self.workdir / "new.sqlite3")
        report = drill_module.verify(snapshot, self.workdir / "new.sqlite3")
        self.assertEqual(report["fence_after"], self.lease["fence"])
        self.assertGreaterEqual(restored["highest_fence"], self.lease["fence"])

    def test_a_restored_database_still_fences_the_original_holder(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        drill_module.restore(snapshot, self.workdir / "new.sqlite3")
        restored = Store(self.workdir / "new.sqlite3")
        with self.assertRaises(Exception):
            restored.renew_lease(self.ana["id"], self.project["id"],
                                 self.lease["id"], self.lease["fence"] - 1, 60)

    def test_restoring_over_a_populated_database_is_refused(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        target = self.workdir / "new.sqlite3"
        drill_module.restore(snapshot, target)
        with self.assertRaises(drill_module.RestoreRefused) as caught:
            drill_module.restore(snapshot, target)
        self.assertIn("two", str(caught.exception))

    def test_a_backup_that_does_not_exist_is_refused(self):
        with self.assertRaises(drill_module.RestoreRefused):
            drill_module.backup(self.root / "missing.sqlite3", self.workdir / "b.sqlite3")
        with self.assertRaises(drill_module.RestoreRefused):
            drill_module.restore(self.root / "missing.sqlite3", self.workdir / "n.sqlite3")

    def test_the_drill_runs_end_to_end_and_refuses_a_second_restore(self):
        report = drill_module.drill(self.database, self.workdir)
        self.assertTrue(report["second_restore_refused"])
        self.assertEqual(report["counts"]["projects"], 1)

    def test_a_tampered_restore_is_detected(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        target = self.workdir / "new.sqlite3"
        drill_module.restore(snapshot, target)
        drill_module._write(target, "DELETE FROM projects")
        with self.assertRaises(drill_module.RestoreRefused) as caught:
            drill_module.verify(snapshot, target)
        self.assertIn("does not match", str(caught.exception))

    def test_a_wrong_fence_is_detected(self):
        snapshot = drill_module.backup(self.database, self.workdir / "b.sqlite3")
        target = self.workdir / "new.sqlite3"
        drill_module.restore(snapshot, target)
        drill_module._write(target, "UPDATE leases SET fence = 0")
        with self.assertRaises(drill_module.RestoreRefused) as caught:
            drill_module.verify(snapshot, target)
        self.assertIn("fence", str(caught.exception))


if __name__ == "__main__":
    unittest.main()