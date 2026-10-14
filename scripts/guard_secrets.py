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


ALLOWED_EMAIL = "jtpydk5gyh-alt@users.noreply.github.com"

# The guard's own tests must contain the shapes they look for. This is the only
# exemption, it is explicit, and it is scoped to that one file.
SELF_EXEMPT = {"tests/test_guard.py"}

PATTERNS = (
    (re.compile(r"@(?!example\.(?:com|invalid|org)|remote\.example|users\.noreply\.github\.com)"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "dirección de correo personal"),
    (re.compile(r"@privaterelay\.appleid\.com"),
     "dirección de correo privada; usa " + ALLOWED_EMAIL),
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


def is_exempt(name: str) -> bool:
    normalised = name.replace("\\", "/")
    return any(normalised == entry or normalised.endswith("/" + entry) for entry in SELF_EXEMPT)


def scan(paths: list[str], revision: str) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for name in paths:
        if name.endswith(ALLOWLIST_SUFFIXES):
            continue
        if is_exempt(name):
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


def identity_findings() -> list[str]:
    problems = []
    for variable in ("user.email", "committer.email"):
        result = subprocess.run(["git", "config", "--get", variable],
                                capture_output=True, text=True, check=False)
        value = result.stdout.strip()
        if value and value != ALLOWED_EMAIL:
            problems.append(f"git {variable} = {value} (debe ser {ALLOWED_EMAIL})")
    return problems


def redact_sample(sample: str) -> str:
    """Removes anything that could be a usable credential from what gets printed.

    A guard that echoes the secret it found has turned a blocked commit into a
    leaked one: the value now sits in the terminal, in CI logs, and in the
    build output of whoever tried to commit it. The location is enough to find
    the value, so only the kind of finding is reported.
    """
    visible = len(sample) - len(sample.lstrip("*_"))
    masked = "*" * min(visible, 4)
    return f"{masked} ({len(sample)} caracteres)"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    include_all = "--all" in arguments
    arguments = [item for item in arguments if item != "--all"]
    explicit = [item for item in arguments if not item.startswith("-")]
    problems = identity_findings()
    findings = scan(tracked_files(include_all, explicit), "HEAD" if include_all else ":")
    if not problems and not findings:
        print(f"guard: sin datos personales; identidad {ALLOWED_EMAIL}")
        return 0
    if problems:
        print("guard: identidad de git incorrecta\n")
        for problem in problems:
            print(f"  {problem}")
        print(f"\n  git config user.email {ALLOWED_EMAIL}")
    if findings:
        print("\nguard: datos personales detectados en ficheros publicables\n")
        for name, number, label, sample in findings:
            print(f"  {name}:{number}  {label}  ->  {redact_sample(sample)}")
        print("\nNo publiques estos datos. Usa un alias, un dominio .example o "
              f"{ALLOWED_EMAIL}.")
    return 1 if problems or findings else 0


if __name__ == "__main__":
    raise SystemExit(main())