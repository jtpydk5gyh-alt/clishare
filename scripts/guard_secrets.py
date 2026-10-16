from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ALLOWED_EMAIL = "jtpydk5gyh-alt@users.noreply.github.com"

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

ALLOWLIST_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf")

CREDENTIAL_NAMES = {
    ".env", ".netrc", ".netrc._ml", ".npmrc", ".pypirc", ".htpasswd",
    "credentials.json", "known_hosts", "id_rsa", "id_dsa", "id_ecdsa",
    "id_ed25519", "shadow",
}
CREDENTIAL_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".crt", ".keystore", ".asc", ".ppk", ".jks",
}
CREDENTIAL_PREFIXES = ("credentials.", "service-account")
CREDENTIAL_ENDS = ("_PRIVATE.md", "_private.md")
CREDENTIAL_STARTS_WITH = (".env.",)
CREDENTIAL_LABEL = "fichero de credenciales por su nombre"


def is_credential_file(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name in CREDENTIAL_NAMES:
        return True
    if name != ".env.example" and any(name.startswith(prefix)
                                       for prefix in CREDENTIAL_STARTS_WITH):
        return True
    if Path(name).suffix.lower() in CREDENTIAL_SUFFIXES:
        return True
    if name.endswith(CREDENTIAL_ENDS):
        return True
    return name.lower().startswith(CREDENTIAL_PREFIXES)


def tracked_files(include_all: bool, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    if include_all:
        arguments = ["ls-files", "-z"]
    else:
        arguments = ["diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"]
    result = subprocess.run(["git", *arguments], capture_output=True, check=False)
    if result.returncode != 0:
        return []
    return [name for name in result.stdout.decode("utf-8", errors="replace").split("\0") if name]


def committed_text(name: str, revision: str) -> str | None:
    prefix = revision[:-1] if revision.endswith(":") else revision
    result = subprocess.run(["git", "show", f"{prefix}:{name}"],
                            capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def is_exempt(name: str) -> bool:
    normalised = name.replace("\\", "/")
    return any(normalised == entry or normalised.endswith("/" + entry) for entry in SELF_EXEMPT)


def scan(paths: list[str], revision: str) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    findings: list[tuple[str, int, str, str]] = []
    unreadable: list[str] = []
    for name in paths:
        if name.endswith(ALLOWLIST_SUFFIXES):
            continue
        if is_exempt(name):
            continue
        if is_credential_file(name):
            findings.append((name, 0, CREDENTIAL_LABEL, ""))
            continue
        text = committed_text(name, revision) if revision else _read_worktree(name)
        if text is None:
            unreadable.append(name)
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append((name, number, label, match.group(0)[:60]))
    return findings, unreadable


def _read_worktree(name: str) -> str | None:
    try:
        return Path(name).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


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
    if not sample:
        return "sin contenido que mostrar"
    visible = len(sample) - len(sample.lstrip("*_"))
    masked = "*" * min(visible, 4)
    return f"{masked} ({len(sample)} caracteres)"


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    arguments = list(sys.argv[1:] if argv is None else argv)
    include_all = "--all" in arguments
    arguments = [item for item in arguments if item != "--all"]
    explicit = [item for item in arguments if not item.startswith("-")]
    problems = identity_findings()
    findings, unreadable = scan(tracked_files(include_all, explicit),
                                "HEAD" if include_all else ":")
    if not problems and not findings and not unreadable:
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
    if unreadable:
        print("\nguard: no se pudo leer el contenido registrado\n")
        for name in unreadable:
            print(f"  {name}")
        print("\nUn fichero que git no entrega no se da por limpio. Revisa el indice.")
    if findings:
        print("\nNo publiques estos datos. Usa un alias, un dominio .example o "
              f"{ALLOWED_EMAIL}.")
    return 1 if problems or findings or unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
