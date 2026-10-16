from __future__ import annotations

import shlex
import stat
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=False)
    if root.returncode != 0:
        print("install_hooks: ejecuta esto dentro de un repositorio git", file=sys.stderr)
        return 1
    repository = Path(root.stdout.strip())
    guard = repository / "scripts" / "guard_secrets.py"
    if not guard.is_file():
        print("install_hooks: no existe el guard en este repositorio", file=sys.stderr)
        return 1
    target = repository / ".git" / "hooks"
    target.mkdir(parents=True, exist_ok=True)
    pre_commit = target / "pre-commit"
    python = shlex.quote(Path(sys.executable).as_posix())
    script = f"#!/bin/sh\nexec {python} {shlex.quote(guard.as_posix())}\n"
    try:
        with pre_commit.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(script)
        pre_commit.chmod(pre_commit.stat().st_mode
                         | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except FileExistsError:
        print("install_hooks: ya existe un hook; no se sobrescribe", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, UnicodeError):
        print("install_hooks: no se pudo instalar el hook", file=sys.stderr)
        return 1
    print(f"install_hooks: hook instalado en {pre_commit}")
    print("install_hooks: el guard se ejecutara en cada commit local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())