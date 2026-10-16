from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class RestoreRefused(Exception):
    pass


def backup(source: Path, destination: Path) -> Path:
    if not source.is_file():
        raise RestoreRefused(f"There is no database at {source}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    origin = sqlite3.connect(source)
    try:
        snapshot = sqlite3.connect(destination)
        try:
            origin.backup(snapshot)
        finally:
            snapshot.close()
    finally:
        origin.close()
    return destination


def _read(database: Path, query: str) -> list:
    connection = sqlite3.connect(database)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def _write(database: Path, query: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(query)
        connection.commit()
    finally:
        connection.close()


def highest_fence(database: Path) -> int:
    rows = _read(database, "SELECT MAX(fence) FROM leases")
    return int(rows[0][0] or 0)


def counts(database: Path) -> dict[str, int]:
    tables = ("users", "projects", "memberships", "leases", "memory", "events")
    found = {row[0] for row in _read(
        database, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {table: (_read(database, f"SELECT COUNT(*) FROM {table}")[0][0]
                    if table in found else 0)
            for table in tables}


def restore(backup_file: Path, target: Path, empty_required: bool = True) -> dict:
    if not backup_file.is_file():
        raise RestoreRefused(f"There is no backup at {backup_file}.")
    if target.exists() and target.is_file() and target.stat().st_size > 0:
        if empty_required:
            populated = _read(
                target, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'")[0][0]
            if populated:
                raise RestoreRefused(
                    "The target already holds a schema. Restoring over it is how two "
                    "authorities come into existence; use an empty database.")
    target.parent.mkdir(parents=True, exist_ok=True)
    origin = sqlite3.connect(backup_file)
    try:
        restored = sqlite3.connect(target)
        try:
            origin.backup(restored)
        finally:
            restored.close()
    finally:
        origin.close()
    return {"target": str(target), "counts": counts(target),
            "highest_fence": highest_fence(target)}


def verify(backup_file: Path, restored: Path) -> dict:
    before, after = counts(backup_file), counts(restored)
    if before != after:
        differing = {table: (before[table], after[table])
                     for table in before if before[table] != after[table]}
        raise RestoreRefused(f"The restore does not match the backup: {differing}")
    original_fence = highest_fence(backup_file)
    restored_fence = highest_fence(restored)
    if restored_fence < original_fence:
        raise RestoreRefused(
            f"The restored database has fence {restored_fence} against the backup's "
            f"{original_fence}; an old holder would validate again.")
    return {"counts": after, "fence_before": original_fence,
            "fence_after": restored_fence,
            "detail": "The restored database carries at least the fence it was taken with."}


def drill(database: Path, workdir: Path) -> dict:
    snapshot = backup(database, workdir / "backup.sqlite3")
    target = workdir / "restored.sqlite3"
    restored = restore(snapshot, target)
    verified = verify(snapshot, target)
    refused = False
    try:
        restore(snapshot, target)
    except RestoreRefused:
        refused = True
    if not refused:
        raise RestoreRefused("A second restore onto the same target was allowed.")
    return {"backup": str(snapshot), "restored": restored["target"],
            "fence_before": verified["fence_before"],
            "fence_after": verified["fence_after"],
            "counts": verified["counts"],
            "second_restore_refused": refused}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="cshcli-restore",
        description="Probar una copia de seguridad y su restauracion.")
    parser.add_argument("--db", default=".cshcli/coordinator.sqlite3")
    parser.add_argument("--workdir", default=".cshcli/restore-drill")
    arguments = parser.parse_args()
    try:
        report = drill(Path(arguments.db), Path(arguments.workdir))
    except RestoreRefused as refusal:
        print(f"restore drill refused: {refusal}", file=__import__("sys").stderr)
        return 1
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("not covered here: a PostgreSQL restore, which needs a real server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())