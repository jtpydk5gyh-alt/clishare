import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import postgres_local
from postgres_local import Cluster, binaries, missing_binaries


class BinaryTests(unittest.TestCase):
    def test_nothing_is_required_when_there_are_no_binaries(self):
        self.assertEqual(missing_binaries(Path("/no/existe")),
                         ["postgres", "pg_ctl", "initdb", "createdb", "psql"])

    def test_the_installed_binaries_are_found_where_pgserver_puts_them(self):
        found = binaries()
        if not found:
            self.skipTest("pgserver is not installed on this machine")
        for name in ("postgres", "initdb", "pg_ctl", "psql"):
            self.assertTrue((found / "postgres.exe").exists() or found.name != "bin", name)
            self.assertEqual(missing_binaries(found), [])

    def test_the_installed_postgres_is_a_real_one(self):
        found = binaries()
        if not found:
            self.skipTest("pgserver is not installed on this machine")
        completed = subprocess.run([str(found / "postgres.exe"), "--version"],
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("postgres", completed.stdout.lower())


class ClusterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name) / "cluster"

    def tearDown(self):
        try:
            Cluster(self.root, port=55433).stop()
        except RuntimeError:
            pass
        self.temp.cleanup()

    def test_a_cluster_without_binaries_is_refused(self):
        with self.assertRaises(RuntimeError) as caught:
            Cluster(self.root, bin_directory=Path("/no/existe"), port=1)
        self.assertIn("binarios", str(caught.exception))

    def test_the_data_directory_is_created_only_once(self):
        if not binaries():
            self.skipTest("pgserver is not installed on this machine")
        cluster = Cluster(self.root, port=55433)
        cluster.start()
        self.assertTrue((self.root / "data" / "PG_VERSION").exists())
        first = cluster.dsn
        self.assertTrue(first.startswith("postgresql://"))
        self.assertIn(str(cluster.port), first)
        self.assertIn("PostgreSQL", cluster.run("SELECT version()"))
        cluster.stop()
        cluster.start()
        self.assertEqual(cluster.dsn, first)


class EnvironmentTests(unittest.TestCase):
    def test_the_dsn_comes_from_the_environment_when_it_is_given(self):
        os.environ["CSHCLI_TEST_DSN"] = "postgresql://alguien@127.0.0.1:1/x"
        self.addCleanup(os.environ.pop, "CSHCLI_TEST_DSN", None)
        self.assertEqual(postgres_local.dsn_from_environment(),
                         "postgresql://alguien@127.0.0.1:1/x")

    def test_without_the_variable_there_is_no_dsn(self):
        os.environ.pop("CSHCLI_TEST_DSN", None)
        self.assertEqual(postgres_local.dsn_from_environment(), None)


if __name__ == "__main__":
    sys.exit(unittest.main())