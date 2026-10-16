from __future__ import annotations

import os
import stat
from pathlib import Path

from .errors import DomainError
from .workspace import Workspace

SKIPPED_DIRECTORIES = {
    ".cshcli", ".eggs", ".git", ".hg", ".idea", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".svn", ".tox", ".venv", ".vscode", "__pycache__", "build",
    "dist", "node_modules", "venv",
}
SKIPPED_SUFFIXES = {
    ".7z", ".bin", ".bmp", ".bz2", ".class", ".dll", ".dylib", ".eot", ".exe",
    ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".mov", ".mp3", ".mp4",
    ".ogg", ".otf", ".pdf", ".png", ".pyc", ".pyo", ".so", ".sqlite3", ".tar",
    ".tgz", ".ttf", ".wav", ".webp", ".whl", ".woff", ".woff2", ".zip",
}
FAVOURITE_PREFIXES = ("README", "docs/", "src/", "tests/", "test/", "app/", "lib/")

SECRET_NAMES = {
    ".env", ".netrc", ".npmrc", ".pypirc", ".htpasswd", "id_rsa", "id_dsa",
    "id_ecdsa", "id_ed25519", "credentials.json", ".netrc._ml", "known_hosts",
}
SECRET_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".crt", ".keystore", ".asc", ".ppk", ".jks",
}
SECRET_CONTAINS = ("service-account", "credential", "_PRIVATE", "_private")
SECRET_STARTS_WITH = (".env.",)

INDEX_LIMIT = 4000
NOTE_LIMIT = 8000
SEARCH_LIMIT = 4000
MATCH_LIMIT = 20
_SNIFF_BYTES = 8192
_LINE_LIMIT = 200
_SEARCH_FOOTER = "Usa /ver <ruta> para ver el archivo entero."
_NOT_OPENING = "Habla con la persona. No tienes que explicar estos bloques."
_FENCE = "```"


def is_secret(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name in SECRET_NAMES:
        return True
    if any(name.startswith(prefix) and name != ".env.example"
           for prefix in SECRET_STARTS_WITH):
        return True
    if Path(name).suffix.lower() in SECRET_SUFFIXES:
        return True
    return any(marker in name for marker in SECRET_CONTAINS)


def _readable_file(target: Path) -> bool:
    if target.suffix.lower() in SKIPPED_SUFFIXES:
        return False
    try:
        metadata = target.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return False
    return True


def _skip_directory(directory: str) -> bool:
    return directory in SKIPPED_DIRECTORIES or directory.endswith(".egg-info")


def _rank(path: str) -> tuple:
    for position, prefix in enumerate(FAVOURITE_PREFIXES):
        if path.startswith(prefix):
            return position, path
    return len(FAVOURITE_PREFIXES), path


def _header(shown: int, total: int) -> str:
    if shown == total:
        return f"Archivos del proyecto actual ({total}):"
    return f"Archivos del proyecto actual ({shown} de {total}; {total - shown} omitidos):"


def _walk(base: Workspace) -> list[str]:
    paths = []
    for directory, subdirectories, files in os.walk(base.root, followlinks=False):
        subdirectories[:] = [name for name in sorted(subdirectories)
                             if not _skip_directory(name)
                             and not os.path.islink(os.path.join(directory, name))]
        for name in files:
            target = Path(directory) / name
            relative = target.relative_to(base.root).as_posix()
            if _readable_file(target) and not is_secret(relative):
                paths.append(relative)
    paths.sort(key=_rank)
    return paths


def index_text(root, limit: int = INDEX_LIMIT) -> str:
    paths = _walk(Workspace(Path(root), "chat"))
    if not paths:
        return ""
    lines, used = [], 0
    for path in paths:
        line = f"- {path}"
        if used + len(line) > limit:
            break
        lines.append(line)
        used += len(line) + 1
    return f"{_header(len(lines), len(paths))}\n" + "\n".join(lines) + \
        "\n" + ("Usa /ver <ruta> para ver uno." if len(lines) < len(paths) else "")


def note_text(root, relative_path: str, limit: int = NOTE_LIMIT) -> str:
    if is_secret(relative_path):
        raise DomainError(403, "secret_refused",
                          "Ese archivo guarda credenciales y no se manda al proveedor.")
    content = Workspace(Path(root), "chat").read(relative_path)
    if b"\x00" in content[:_SNIFF_BYTES]:
        raise DomainError(415, "not_text", "Ese archivo no es texto y no se puede mostrar aquí.")
    text = content.decode("utf-8", errors="replace")
    head = f"{_NOT_OPENING}\n\nArchivo '{relative_path}' del proyecto actual:\n\n"
    room = max(0, limit - len(head) - len(_FENCE) * 2 - 2)
    if len(text) > room:
        notice = f"\n… (el archivo continúa; se muestran {room} de {len(text)} caracteres)"
        room = max(0, room - len(notice))
        clipped = text[:room] + notice
    else:
        clipped = text
    return f"{head}{_FENCE}\n{clipped}\n{_FENCE}"


def _matches(base: Workspace, path: str, needle: str, found: list, room: int) -> int:
    try:
        content = base.read(path)
    except DomainError:
        return 0
    if b"\x00" in content[:_SNIFF_BYTES]:
        return 0
    total = 0
    for number, line in enumerate(content.decode("utf-8", errors="replace").splitlines(), start=1):
        if needle in line.casefold():
            total += 1
            if len(found) < room:
                found.append(f"- {path}:{number}: {line.strip()[:_LINE_LIMIT]}")
    return total


def _search_header(shown: int, total: int, query: str) -> str:
    name = "coincidencia" if total == 1 else "coincidencias"
    where = "en el proyecto actual"
    if shown == total:
        return f"{total} {name} de {query!r} {where}"
    return f"{shown} de {total} {name} de {query!r} {where}; {total - shown} más"


def search_text(root, query: str, limit: int = SEARCH_LIMIT, matches: int = MATCH_LIMIT) -> str:
    if not isinstance(query, str) or not query.strip():
        raise DomainError(400, "empty_query", "Escribe el texto que quieres buscar.")
    base = Workspace(Path(root), "chat")
    needle = query.strip().casefold()
    found: list = []
    total = 0
    for path in _walk(base):
        total += _matches(base, path, needle, found, matches)
    if not found:
        return ""
    head = _search_header(len(found), total, query.strip())
    room = max(0, limit - len(head) - len(_SEARCH_FOOTER) - 1)
    lines, used = [], 0
    for line in found:
        if used + len(line) > room:
            break
        lines.append(line)
        used += len(line) + 1
    return f"{head}\n" + "\n".join(lines) + "\n" + _SEARCH_FOOTER