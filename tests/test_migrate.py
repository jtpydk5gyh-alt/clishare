import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate


class MigrationFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def write(self, name, content):
        target = self.folder / name
        target.write_text(content, encoding="utf-8", newline="\n")
        return target

    def test_a_file_that_drops_is_never_an_up_migration(self):
        self.write("002.sql", "DROP TABLE IF EXISTS users;")
        self.assertEqual(migrate.up_migrations(self.folder), [])

    def test_a_rollback_file_is_never_an_up_migration(self):
        self.write("002.down.sql", "SELECT 1;")
        self.assertEqual(migrate.up_migrations(self.folder), [])

    def test_up_migrations_come_back_in_order(self):
        self.write("002.sql", "SELECT 2;")
        self.write("001.sql", "SELECT 1;")
        self.write("001.down.sql", "SELECT 0;")
        self.assertEqual([p.name for p in migrate.up_migrations(self.folder)],
                         ["001.sql", "002.sql"])

    def test_an_empty_folder_has_no_migrations(self):
        self.assertEqual(migrate.up_migrations(self.folder), [])

    def test_a_missing_folder_is_refused_rather_than_read(self):
        with self.assertRaises(migrate.MigrationError) as caught:
            migrate.up_migrations(self.folder / "no-existe")
        self.assertIn("no-existe", str(caught.exception))


class PathHygieneTests(unittest.TestCase):
    def test_scripts_never_shadow_the_cshcli_package(self):
        needle = 'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))'
        here = Path(__file__).resolve().name
        offenders = [path.name for path
                     in sorted(Path(__file__).resolve().parent.glob("test_*.py"))
                     if path.name != here and needle in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [],
                         "scripts/ delante de src/ hace que un proceso hijo importe "
                         "scripts/cshcli.py en vez del paquete, y el fallo aparece "
                         "lejos de su causa: usa sys.path.append")

    def test_importing_cshcli_yields_the_package_not_the_script(self):
        import cshcli
        self.assertTrue(hasattr(cshcli, "__path__"),
                        "cshcli debe ser un paquete, no scripts/cshcli.py")


class RepositoryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parents[1] / "migrations"

    def test_the_repository_migration_is_appliable(self):
        files = migrate.up_migrations(self.folder)
        self.assertTrue(files, "no hay migraciones de subida en el repositorio")

    def test_the_repository_migration_does_not_drop_anything(self):
        for path in migrate.up_migrations(self.folder):
            body = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("drop table", body, path.name)
            self.assertNotIn("drop sequence", body, path.name)

    def test_the_repository_has_a_rollback_separated_from_the_up(self):
        self.assertTrue(list(self.folder.glob("*.down.sql")),
                        "el rollback tiene que vivir aparte de la subida")

    def test_no_timestamp_column_is_single_precision(self):
        for path in migrate.up_migrations(self.folder):
            body = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                body, r"\bREAL\b",
                f"{path.name} usa REAL, que en PostgreSQL es float4: un instante "
                "Unix de este siglo necesita 13 cifras y float4 solo guarda 7, "
                "asi que una caducidad de 60 s se redondea a los 128 s mas "
                "cercanos. El esquema remoto usa DOUBLE PRECISION.")

    def test_the_time_columns_keep_double_precision(self):
        body = migrate.up_migrations(self.folder)[0].read_text(encoding="utf-8")
        self.assertIn("DOUBLE PRECISION", body)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ.get("CSHCLI_TEST_DSN", "").strip()

    def test_without_a_server_the_test_says_why_it_skips(self):
        if not self.dsn:
            self.skipTest("no hay CSHCLI_TEST_DSN: levanta el clúster con "
                          "python scripts/postgres_local.py start")
        import psycopg
        psycopg.connect(self.dsn, connect_timeout=10).close()


if __name__ == "__main__":
    sys.exit(unittest.main())