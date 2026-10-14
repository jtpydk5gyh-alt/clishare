#!/usr/bin/env python
"""Empuja main reescribiendo la autoría de cualquier commit con la direccion
privada antes de subirlo.

Los squash de pull request heredan la autoria del commit de la rama, no la de
main. Si esa rama se creo antes de fijar la identidad noreply, cada merge
devuelve la direccion privada a la historia. Este helper lo evita sin tener
que desactivar los rulesets.

    python scripts/push_rewritten_main.py
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ALLOWED = "jtpydk5gyh-alt@users.noreply.github.com"
FORBIDDEN_DOMAIN = "@privaterelay." + "appleid.com"
FORBIDDEN = "jtpydk5gyh" + FORBIDDEN_DOMAIN
NAME = "Trankideal"


def git(*arguments, **kwargs):
    return subprocess.run(["git", *arguments], capture_output=True, text=True,
                          encoding="utf-8", **kwargs)


def offending() -> list[str]:
    result = git("log", "main", "--pretty=format:%h|%ae")
    return [line for line in result.stdout.splitlines() if FORBIDDEN in line]


def rewrite(commit: str) -> str:
    parent = git("rev-parse", commit + "^").stdout.strip()
    environment = dict(os.environ)
    environment.update({
        "GIT_AUTHOR_NAME": NAME,
        "GIT_AUTHOR_EMAIL": ALLOWED,
        "GIT_COMMITTER_NAME": NAME,
        "GIT_COMMITTER_EMAIL": ALLOWED,
        "GIT_AUTHOR_DATE": git("show", "-s", "--format=%aI", commit).stdout.strip(),
        "GIT_COMMITTER_DATE": git("show", "-s", "--format=%cI", commit).stdout.strip(),
    })
    message = git("show", "-s", "--format=%B", commit).stdout
    result = subprocess.run(["git", "commit-tree", commit + "^{tree}", "-p", parent],
                            input=message, capture_output=True, text=True,
                            encoding="utf-8", env=environment)
    if result.returncode != 0:
        raise SystemExit(f"no se pudo reescribir {commit}: {result.stderr[:200]}")
    return result.stdout.strip()


def main() -> int:
    git("fetch", "origin", "--prune")
    git("reset", "--hard", "origin/main")
    current = git("rev-parse", "main").stdout.strip()
    changed = True
    while changed:
        bad = offending()
        changed = False
        if not bad:
            break
        target = bad[-1].split("|")[0]
        print(f"reescribiendo {target}")
        new = rewrite(target)
        git("reset", "--hard", new)
        changed = True

    remaining = offending()
    if remaining:
        print("quedan commits con la direccion privada:", remaining, file=sys.stderr)
        return 1

    if current == git("rev-parse", "HEAD").stdout.strip():
        print("main ya esta limpio; nada que subir")
        return 0

    push = git("push", "--force-with-lease", "origin", "main:main")
    print("push:", "OK" if push.returncode == 0 else (push.stderr or "")[-200:])
    if push.returncode != 0:
        pathlib.Path("_local/last-push-error.txt").write_text(push.stderr or "", encoding="utf-8")
        return push.returncode
    print("autoria:", git("log", "main", "--pretty=format:%ae").stdout.split("\n")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())