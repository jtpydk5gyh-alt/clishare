from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERSION = re.compile(r"0\.\d+\.\d+")

TARGETS = (
    ("src/cshcli/__init__.py", re.compile(r'(__version__ = ")(0\.\d+\.\d+)(")')),
    ("pyproject.toml", re.compile(r'(?m)^(version = ")(0\.\d+\.\d+)(")$')),
    ("README.md", re.compile(r"(version )(0\.\d+\.\d+)(\.)")),
    ("docs/STATUS.md", re.compile(r"(Version \*\*)(0\.\d+\.\d+)(\*\*)")),
    ("docs/STATUS.md", re.compile(r"(Help and )(0\.\d+\.\d+)( version verified)")),
    ("docs/USAGE.md", re.compile(r"(local )(0\.\d+\.\d+)( pilot)")),
    ("docs/CONTEXT.md", re.compile(r"(\*\*Versión )(0\.\d+\.\d+)(, construida)")),
    ("docs/CONTEXT.md", re.compile(r"(\| Versión \| `)(0\.\d+\.\d+)(`)")),
    ("docs/CONTEXT.md", re.compile(r"(\*\*Hecho\*\*: `)(0\.\d+\.\d+)(` con checksum)")),
)


class BumpRefused(Exception):
    pass


def parse(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise BumpRefused(f"{value} is not a three part version")
    return tuple(int(part) for part in value.split("."))


def read_current() -> str:
    text = (ROOT / "src" / "cshcli" / "__init__.py").read_text(encoding="utf-8")
    found = VERSION.search(text)
    if not found:
        raise BumpRefused("no version found in src/cshcli/__init__.py")
    return found.group()


def rewrite(name: str, pattern: re.Pattern[str], old: str, new: str) -> int:
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise BumpRefused(
            f"{name} has {len(matches)} matches for {pattern.pattern}, expected 1; "
            "the wording changed and this script needs the new sentence")
    updated = pattern.sub(lambda m: m.group(1) + new + m.group(3), text, count=1)
    path.write_text(updated, encoding="utf-8")
    return 1


def changelog_entry(new: str) -> bool:
    path = ROOT / "CHANGELOG.md"
    if not path.exists():
        return False
    return bool(re.search(r"(?m)^## \[?" + re.escape(new) + r"\]?", path.read_text(encoding="utf-8")))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/bump_version.py X.Y.Z", file=sys.stderr)
        return 2
    try:
        new = sys.argv[1]
        new_key = parse(new)
        old = read_current()
        old_key = parse(old)
        if new_key <= old_key:
            raise BumpRefused(f"{new} does not move forward from {old}")
        touched = [name for name, _ in TARGETS]
        for name, pattern in TARGETS:
            rewrite(name, pattern, old, new)
    except (BumpRefused, FileNotFoundError) as refusal:
        print(f"bump refused: {refusal}", file=sys.stderr)
        return 1
    print(f"cshcli {old} -> {new} in {len(TARGETS)} places")
    for name in dict.fromkeys(touched):
        print(f"  {name}")
    if not changelog_entry(new):
        print(f"warning: CHANGELOG.md has no entry for {new}")
    print(f"still to do by hand: the CHANGELOG entry, git tag v{new}, and the commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())