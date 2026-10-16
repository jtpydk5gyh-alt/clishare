import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import postgres_local
from postgres_local import Cluster

DSN = os.environ.get("CSHCLI_REMOTE_DSN", "")

SKIP_REASON = (
    "requires a real PostgreSQL: set CSHCLI_REMOTE_DSN. The drill was only ever "
    "run against SQLite, so restoring a real database is unproven here."
)


class RestoreDrillTests(unittest.TestCase):
    def setUp(self):
        if not DSN:
            self.skipTest(SKIP_REASON)
        try:
            import psycopg
            psycopg.connect(DSN, connect_timeout=10).close()
        except Exception as error:
            self.skipTest(f"{SKIP_REASON} ({type(error).__name__})")
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "copia.dump"
        self.target = f"cshcli_restore_{uuid.uuid4().hex[:8]}"
        self.cluster = Cluster(port=postgres_local.DEFAULT_PORT)
        self.addCleanup(self._drop_target)
        self.marker = f"drill-{uuid.uuid4().hex[:8]}"

    def _drop_target(self):
        try:
            self.cluster.run(f"DROP DATABASE IF EXISTS {self.target}")
        except Exception:
            pass

    def _table_names(self, database):
        import psycopg
        with psycopg.connect(self._dsn(database)) as connection:
            rows = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name").fetchall()
            return [row[0] for row in rows]

    def _dsn(self, database):
        return f"postgresql://cshcli@127.0.0.1:{postgres_local.DEFAULT_PORT}/{database}"

    def _plant(self):
        import psycopg
        user_id = f"user-{self.marker}"
        with psycopg.connect(self._dsn(postgres_local.DATABASE)) as connection:
            connection.execute(
                "INSERT INTO users(id, name, name_key, token_hash) VALUES (%s,%s,%s,%s)",
                (user_id, "d", f"k-{self.marker}", f"t-{self.marker}"))
            connection.execute(
                "INSERT INTO projects(id, name, name_key, owner_id) VALUES (%s,%s,%s,%s)",
                (self.marker, "p", f"pk-{self.marker}", user_id))
        return user_id

    def _count(self, database, table):
        import psycopg
        with psycopg.connect(self._dsn(database)) as connection:
            return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def _has_project(self, database, project_id):
        import psycopg
        with psycopg.connect(self._dsn(database)) as connection:
            return connection.execute(
                "SELECT count(*) FROM projects WHERE id = %s", (project_id,)).fetchone()[0]

    def test_a_dump_restores_into_an_empty_database(self):
        self._plant()
        self.cluster.dump(self.archive, database=postgres_local.DATABASE)
        self.assertTrue(self.archive.exists())
        self.assertGreater(self.archive.stat().st_size, 0)
        before = sorted(self._table_names(postgres_local.DATABASE))
        self.cluster.create_empty_database(self.target)
        self.assertEqual(self._table_names(self.target), [])
        self.cluster.restore(self.archive, self.target)
        self.assertEqual(sorted(self._table_names(self.target)), before)
        self.assertEqual(self._has_project(self.target, self.marker), 1)

    def test_the_restore_does_not_lose_rows(self):
        self._plant()
        self.cluster.dump(self.archive, database=postgres_local.DATABASE)
        self.cluster.create_empty_database(self.target)
        self.cluster.restore(self.archive, self.target)
        for table in ("users", "projects", "leases", "events", "memory"):
            self.assertEqual(self._count(self.target, table),
                             self._count(postgres_local.DATABASE, table), table)

    def test_restoring_over_a_populated_database_is_refused(self):
        self._plant()
        self.cluster.dump(self.archive, database=postgres_local.DATABASE)
        self.cluster.create_empty_database(self.target)
        self.cluster.restore(self.archive, self.target)
        with self.assertRaises(RuntimeError) as caught:
            self.cluster.restore(self.archive, self.target)
        self.assertIn("pg_restore", str(caught.exception))

    def test_the_fence_sequence_never_goes_backwards_after_a_restore(self):
        import psycopg
        self._plant()
        self.cluster.dump(self.archive, database=postgres_local.DATABASE)
        with psycopg.connect(self._dsn(postgres_local.DATABASE)) as connection:
            before = connection.execute(
                "SELECT last_value FROM lease_fence_sequence").fetchone()[0]
        self.cluster.create_empty_database(self.target)
        self.cluster.restore(self.archive, self.target)
        with psycopg.connect(self._dsn(self.target)) as connection:
            restored = connection.execute(
                "SELECT last_value FROM lease_fence_sequence").fetchone()[0]
        self.assertGreaterEqual(int(restored), int(before),
                                "restaurar no puede devolver el fence hacia atras")


if __name__ == "__main__":
    sys.exit(unittest.main())