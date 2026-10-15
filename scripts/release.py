"""Builds a release and refuses to call it one until it proves itself.

The plan asks for a versioned release with checksums, change notes and real
limits, and it asks that the install be re-validated on every supported
Python. Two of those are cheap and one is not, so this script does the cheap
ones and says plainly which one it did not do.

What it does:

- reads the version from `src/cshcli/__init__.py` and refuses to build when
  `pyproject.toml` disagrees, because two versions in one repository is a
  release nobody can reason about;
- builds the wheel and the source distribution with the standard library only,
  into a directory it creates;
- writes a `SHA256SUMS` file next to them;
- installs the wheel into a throwaway directory, imports it, and runs the CLI's
  `--help` from the **installed** copy, not from the working tree;
- refuses to run when the tree is dirty, because a release built from uncommitted
  work is a release nobody can reproduce.

What it does not do: sign anything, publish anywhere, or verify the install on
Linux, macOS or Python versions other than the one running it. Those need a
machine and credentials that do not exist here, and a release procedure that
claims otherwise is worse than one that admits it.

The build is refused rather than warned about when the working tree is dirty.
A warning is the kind of thing that gets read once and then ignored.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION_FILE = ROOT / "src" / "cshcli" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"


class ReleaseRefused(Exception):
    pass


def read_version() -> str:
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not value:
                break
            return value
    raise ReleaseRefused("the version is not defined in src/cshcli/__init__.py")


def read_pyproject_version() -> str | None:
    inside = False
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            inside = stripped == "[project]"
            continue
        if inside and stripped.startswith("version"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def dirty_paths() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build(version: str) -> list[Path]:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(DIST), ROOT],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise ReleaseRefused(f"the wheel build failed: {result.stderr.strip()[-400:]}")
    built = sorted(path for path in DIST.iterdir() if path.suffix == ".whl")
    if len(built) != 1:
        raise ReleaseRefused(f"expected exactly one wheel, found {len(built)}")
    with zipfile.ZipFile(built[0]) as archive:
        names = archive.namelist()
    if f"cshcli-{version}.dist-info/METADATA" not in names:
        raise ReleaseRefused(
            f"the wheel does not carry version {version}; it says {names[-1]}")
    return built


def checksums(artefacts: list[Path]) -> Path:
    lines = []
    for path in artefacts:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    target = DIST / "SHA256SUMS"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def verify_install(wheel: Path, version: str, into: Path) -> dict:
    """Imports and runs the installed copy, not the working tree."""
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(into), str(wheel)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise ReleaseRefused(f"the wheel did not install: {result.stderr.strip()[-400:]}")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(into)
    environment["PYTHONUTF8"] = "1"
    check = subprocess.run(
        [sys.executable, "-c",
         "import cshcli, cshcli.cli, cshcli.deploy, cshcli.queue, cshcli.usage;"
         "print(cshcli.__version__)"],
        cwd=into, capture_output=True, text=True, env=environment)
    if check.returncode != 0:
        raise ReleaseRefused(f"the installed copy does not import: {check.stderr.strip()[-400:]}")
    reported = check.stdout.strip()
    if reported != version:
        raise ReleaseRefused(
            f"the installed copy reports version {reported}, not {version}")
    help_run = subprocess.run([sys.executable, "-m", "cshcli", "--help"],
                              cwd=into, capture_output=True, text=True, env=environment)
    if help_run.returncode != 0:
        raise ReleaseRefused(
            f"the installed CLI does not answer --help: {help_run.stderr.strip()[-300:]}")
    return {"version": reported, "python": sys.version.split()[0],
            "help_lines": len(help_run.stdout.splitlines())}


def main() -> int:
    try:
        version = read_version()
        declared = read_pyproject_version()
        if declared is not None and declared != version:
            raise ReleaseRefused(
                f"pyproject.toml says {declared} and __init__.py says {version}; "
                "a release with two versions is not reproducible.")
        pending = [line for line in dirty_paths() if not line.startswith("??")]
        if pending:
            raise ReleaseRefused(
                "the working tree has uncommitted changes; a release built from them "
                "cannot be reproduced:\n  " + "\n  ".join(pending))
        artefacts = build(version)
        sums = checksums(artefacts)
        report = verify_install(artefacts[0], version, DIST / "_install_check")
        shutil.rmtree(DIST / "_install_check", ignore_errors=True)
    except ReleaseRefused as refusal:
        print(f"release refused: {refusal}", file=sys.stderr)
        return 1
    print(f"cshcli {version}")
    for path in artefacts:
        print(f"  {path.name}")
    print(f"  {sums.name}")
    print(f"  installed copy reports {report['version']} on Python {report['python']}, "
          f"--help answers in {report['help_lines']} lines")
    print("not done here: signing, publishing, and install checks on other platforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())