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
INDEX_LIMIT = 4000
NOTE_LIMIT = 8000
_SNIFF_BYTES = 8192
_NOT_OPENING = "Habla con la persona. No tienes que explicar estos bloques."
_FENCE = "```"


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


def index_text(root, limit: int = INDEX_LIMIT) -> str:
    base = Workspace(Path(root), "chat")
    paths = []
    for directory, subdirectories, files in os.walk(base.root, followlinks=False):
        subdirectories[:] = [name for name in sorted(subdirectories)
                             if not _skip_directory(name)
                             and not os.path.islink(os.path.join(directory, name))]
        for name in files:
            target = Path(directory) / name
            if _readable_file(target):
                paths.append(target.relative_to(base.root).as_posix())
    if not paths:
        return ""
    paths.sort(key=_rank)
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