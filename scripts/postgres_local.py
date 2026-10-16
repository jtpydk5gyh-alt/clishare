from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.home() / "cshcli-pg" / "cluster"
DEFAULT_PORT = 55432
DATABASE = "cshcli"
USER = "cshcli"
REQUIRED = ("postgres", "pg_ctl", "initdb", "createdb", "psql")


def binaries():
    try:
        import pgserver
    except ImportError:
        return None
    candidate = Path(pgserver.__file__).parent / "pginstall" / "bin"
    return candidate if candidate.is_dir() else None


def missing_binaries(directory: Path) -> list:
    return [name for name in REQUIRED
            if not (Path(directory) / f"{name}.exe").exists()
            and not (Path(directory) / name).exists()]


def dsn_from_environment():
    value = os.environ.get("CSHCLI_TEST_DSN", "").strip()
    return value or None


def _run(command: list, timeout: int = 120) -> subprocess.CompletedProcess:
    scratch = tempfile.mkdtemp(prefix="cshcli-pg-")
    out_path = Path(scratch) / "out.txt"
    err_path = Path(scratch) / "err.txt"
    try:
        with out_path.open("wb") as out, err_path.open("wb") as err:
            code = subprocess.run(command, stdout=out, stderr=err, timeout=timeout).returncode
    except OSError as error:
        raise RuntimeError(f"no se pudo ejecutar {command[0]}: {error}") from None
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "",
                                           "el comando no respondio a tiempo")
    result = subprocess.CompletedProcess(
        command, code,
        out_path.read_text(encoding="utf-8", errors="replace"),
        err_path.read_text(encoding="utf-8", errors="replace"))
    shutil.rmtree(scratch, ignore_errors=True)
    return result


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


class Cluster:
    def __init__(self, root: Path = ROOT, port: int = DEFAULT_PORT,
                 bin_directory: Path | None = None):
        self.root = Path(root)
        self.port = int(port)
        self.bin_directory = Path(bin_directory) if bin_directory else binaries()
        if self.bin_directory is None:
            raise RuntimeError(
                "hacen falta los binarios de PostgreSQL: pip install pgserver")
        absent = missing_binaries(self.bin_directory)
        if absent:
            raise RuntimeError(
                "faltan binarios de PostgreSQL: " + ", ".join(absent))

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def log(self) -> Path:
        return self.root / "postgres.log"

    @property
    def dsn(self) -> str:
        return f"postgresql://{USER}@127.0.0.1:{self.port}/{DATABASE}"

    def _binary(self, name: str) -> str:
        for candidate in (f"{name}.exe", name):
            if (self.bin_directory / candidate).exists():
                return str(self.bin_directory / candidate)
        raise RuntimeError(f"falta el binario {name}")

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        completed = _run([self._binary("initdb"), "-D", str(self.data),
                          "-U", USER, "-A", "trust", "--encoding=UTF8",
                          "--locale=C"], timeout=300)
        if completed.returncode != 0:
            raise RuntimeError(f"initdb fallo: {completed.stderr.strip()}")

    def _create_database(self) -> None:
        completed = _run([self._binary("createdb"), "-h", "127.0.0.1",
                          "-p", str(self.port), "-U", USER, DATABASE])
        if completed.returncode != 0 and "already exists" not in completed.stderr:
            raise RuntimeError(f"createdb fallo: {completed.stderr.strip()}")

    def start(self) -> "Cluster":
        if not (self.data / "PG_VERSION").exists():
            self.create()
        if not _port_is_free(self.port):
            return self
        completed = _run([self._binary("pg_ctl"), "-D", str(self.data),
                          "-l", str(self.log), "-w", "-t", "60",
                          "-o", f"-p {self.port} -h 127.0.0.1",
                          "start"], timeout=180)
        if completed.returncode != 0:
            raise RuntimeError(f"pg_ctl start fallo: {completed.stderr.strip()}")
        self._create_database()
        return self

    def stop(self) -> None:
        if not (self.data / "PG_VERSION").exists():
            return
        completed = _run([self._binary("pg_ctl"), "-D", str(self.data), "-m", "immediate",
                          "-w", "-t", "30", "stop"], timeout=90)
        if completed.returncode == 0:
            return
        self._kill_postmaster()

    def _postmaster_pid(self) -> int | None:
        marker = self.data / "postmaster.pid"
        if not marker.exists():
            return None
        try:
            first = marker.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            return int(first.strip())
        except (OSError, ValueError, IndexError):
            return None

    def _kill_postmaster(self) -> None:
        pid = self._postmaster_pid()
        if pid is None:
            return
        _run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)
        for _ in range(60):
            if not (self.data / "postmaster.pid").exists():
                return
            time.sleep(0.5)

    def destroy(self) -> None:
        self.stop()
        shutil.rmtree(self.data, ignore_errors=True)

    def run(self, sql: str, database: str = DATABASE, timeout: int = 60) -> str:
        completed = _run([self._binary("psql"), "-h", "127.0.0.1", "-p", str(self.port),
                          "-U", USER, "-d", database, "-t", "-A", "-c", sql], timeout)
        if completed.returncode != 0:
            raise RuntimeError(f"psql fallo: {completed.stderr.strip()}")
        return completed.stdout.strip()

    def dump(self, target: Path, database: str = DATABASE) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = _run([self._binary("pg_dump"), "-h", "127.0.0.1", "-p", str(self.port),
                          "-U", USER, "-d", database, "-Fc", "-f", str(target)], timeout=600)
        if completed.returncode != 0:
            raise RuntimeError(f"pg_dump fallo: {completed.stderr.strip()}")
        return target

    def restore(self, archive: Path, database: str) -> None:
        completed = _run([self._binary("pg_restore"), "-h", "127.0.0.1", "-p", str(self.port),
                          "-U", USER, "-d", database, "--exit-on-error",
                          str(archive)], timeout=600)
        if completed.returncode != 0:
            raise RuntimeError(f"pg_restore fallo: {completed.stderr.strip()}")

    def create_empty_database(self, database: str) -> None:
        completed = _run([self._binary("createdb"), "-h", "127.0.0.1", "-p", str(self.port),
                          "-U", USER, database])
        if completed.returncode != 0 and "already exists" not in completed.stderr:
            raise RuntimeError(f"createdb fallo: {completed.stderr.strip()}")


def main(argv: list) -> int:
    action = argv[1] if len(argv) > 1 else "start"
    if action in {"-h", "--help"}:
        print("usage: postgres_local.py start|stop|dsn|destroy")
        return 0
    try:
        cluster = Cluster()
        if action == "start":
            cluster.start()
        elif action == "stop":
            cluster.stop()
        elif action == "destroy":
            cluster.destroy()
        elif action == "dsn":
            print(cluster.dsn)
            return 0
        else:
            print(f"accion desconocida: {action}", file=sys.stderr)
            return 2
    except RuntimeError as error:
        print(f"postgres_local: {error}", file=sys.stderr)
        return 1
    print(cluster.dsn)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))