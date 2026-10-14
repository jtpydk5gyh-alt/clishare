"""Installs the personal data guard as a local pre-commit hook.

    python scripts/install_hooks.py

The hook is not tracked by git: it belongs to your machine, like the other
local rules. It runs the guard against the staged content on every commit.
"""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path


HOOK = """#!/bin/sh
exec "{python}" "{guard}"
"""


def main() -> int:
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=False)
    if root.returncode != 0:
        print("install_hooks: ejecuta esto dentro de un repositorio git")
        return 1
    hooks = Path(root.stdout.strip()) / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-commit"
    script = HOOK.format(python=sys.executable,
                         guard=(root.stdout.strip() / "scripts" / "guard_secrets.py").as_posix())
    target.write_text(script, encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"install_hooks: hook instalado en {target}")
    print("install_hooks: el guard se ejecutara en cada commit local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())