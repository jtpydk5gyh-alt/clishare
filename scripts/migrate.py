from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
EXPECTED_TABLES = ("users", "projects", "memberships", "invitations", "leases",
                   "memory", "authorization_grants", "sessions", "events")
DESTRUCTIVE = ("drop table", "drop sequence", "drop schema", "truncate ")


class MigrationError(RuntimeError):
    pass


def up_migrations(folder: Path = MIGRATIONS) -> list:
    folder = Path(folder)
    if not folder.is_dir():
        raise MigrationError(f"no hay carpeta de migraciones: {folder}")
    files = [path for path in sorted(folder.glob("*.sql"))
             if not path.name.endswith(".down.sql")]
    return [path for path in files if not _is_destructive(path)]


def _is_destructive(path: Path) -> bool:
    body = path.read_text(encoding="utf-8", errors="replace").lower()
    return any(marker in body for marker in DESTRUCTIVE)


def dsn_from_environment() -> str:
    value = os.environ.get("CSHCLI_REMOTE_DSN") or os.environ.get("CSHCLI_TEST_DSN") or ""
    return value.strip()


def tables(connection) -> list:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'").fetchall()
    return sorted(row[0] for row in rows)


def missing_tables(connection) -> list:
    present = set(tables(connection))
    return [name for name in EXPECTED_TABLES if name not in present]


def apply(dsn: str, folder: Path = MIGRATIONS) -> list:
    if not dsn:
        raise MigrationError("falta el DSN: pon CSHCLI_REMOTE_DSN")
    try:
        import psycopg
    except ImportError:
        raise MigrationError("falta el driver: pip install 'cshcli[remote]'") from None
    try:
        connection = psycopg.connect(dsn, connect_timeout=15)
    except Exception as error:
        raise MigrationError(f"no se pudo conectar: {error}") from None
    applied = []
    try:
        connection.autocommit = True
        for path in up_migrations(folder):
            connection.execute(path.read_text(encoding="utf-8"))
            applied.append(path.name)
        absent = missing_tables(connection)
        if absent:
            raise MigrationError("faltan tablas tras migrar: " + ", ".join(absent))
    finally:
        connection.close()
    return applied


def main(argv: list) -> int:
    if len(argv) > 1 and argv[1] in {"-h", "--help"}:
        print("usage: migrate.py [DSN]")
        return 0
    dsn = argv[1] if len(argv) > 1 else dsn_from_environment()
    try:
        applied = apply(dsn)
    except MigrationError as error:
        print(f"migrate: {error}", file=sys.stderr)
        return 1
    print(f"aplicadas {len(applied)}: {', '.join(applied) if applied else 'ninguna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))