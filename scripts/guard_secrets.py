"""Fails when a tracked file would publish personal data.

Run it before every commit and in CI. It scans the files that git is about to
record, not the working tree, so an unrelated local file cannot fail the build.

    python scripts/guard_secrets.py            # staged changes
    python scripts/guard_secrets.py --all      # everything tracked
    python scripts/guard_secrets.py --staged FILE...
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|invalid)|remote\.example)"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "dirección de correo personal"),
    (re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+/"),
     "ruta de usuario del sistema"),
    (re.compile(r"/home/[A-Za-z0-9._-]+/|C:\\\\Users\\\\"),
     "ruta de usuario del sistema"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"),
     "token de API o GitHub"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "clave privada"),
)

ALLOWLIST_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".whl", ".sqlite3", ".pyc")


def tracked_files(include_all: bool, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    arguments = ["ls-files"] if include_all else ["diff", "--cached", "--name-only", "--diff-filter=ACM"]
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def committed_text(name: str, revision: str) -> str | None:
    result = subprocess.run(["git", "show", f"{revision}:{name}"],
                            capture_output=True, text=True, check=False, encoding="utf-8",
                            errors="strict")
    if result.returncode != 0:
        return None
    return result.stdout


def scan(paths: list[str], revision: str) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for name in paths:
        if name.endswith(ALLOWLIST_SUFFIXES):
            continue
        if not Path(name).exists():
            continue
        text = committed_text(name, revision)
        if text is None:
            try:
                text = Path(name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append((name, number, label, match.group(0)[:60]))
    return findings


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    include_all = "--all" in arguments
    arguments = [item for item in arguments if item != "--all"]
    explicit = [item for item in arguments if not item.startswith("-")]
    findings = scan(tracked_files(include_all, explicit), "HEAD" if include_all else ":")
    if not findings:
        print("guard: sin datos personales en los ficheros revisados")
        return 0
    print("guard: datos personales detectados en ficheros publicables\n")
    for name, number, label, sample in findings:
        print(f"  {name}:{number}  {label}  ->  {sample}")
    print("\nNo publiques estos datos. Usa un alias, un dominio .example o "
          "una direccion noreply de GitHub.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())