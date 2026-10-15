"""Checking for an update, and installing one only when asked twice.

The owner asked for self-updating. Installing code without being asked is a
bad idea even when the code is ours, and here there is a concrete reason rather
than a principle: installing from `main` is installing code that is neither
versioned nor reviewed. A tool that quietly fetched that would be worse than no
updater at all.

So `update` is two commands wearing one name:

- `cshcli update` **compares and reports**. It changes nothing on disk.
- `cshcli update --apply` asks you to type the version, then verifies the
  checksum of what it downloaded **before** touching anything already installed.

The checksum matters because the install path the owner asked about is a zip
from GitHub. Anyone serving that path can put anything in it. `verify` exists
because a download that fails verification must leave no trace, not a
half-installed package.

Both halves refuse to act on a branch other than `main`, and neither can turn
an unverified artefact into an installed one.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .errors import DomainError


REPOSITORY = "jtpydk5gyh-alt/cshcli"
ARCHIVE_ROOT = f"https://github.com/{REPOSITORY}/archive/refs/heads/main.zip"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_DOWNLOAD = 80 * 1024 * 1024


class UpdateUnavailable(Exception):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str):
        raise UpdateUnavailable("a version must be text")
    cleaned = value.strip().lstrip("vV")
    parts = cleaned.split(".")
    if len(parts) != 3:
        raise UpdateUnavailable(f"cannot read {value!r} as a version")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise UpdateUnavailable(f"cannot read {value!r} as a version") from None


def newest_remote_version(opener=urllib.request.urlopen) -> str | None:
    """Returns the published version, or None when there is no release."""
    request = urllib.request.Request(
        RELEASES_API, headers={"Accept": "application/vnd.github+json",
                               "User-Agent": "cshcli"})
    try:
        with opener(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise UpdateUnavailable(f"GitHub answered HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("GitHub could not be reached") from None
    except (ValueError, UnicodeError):
        raise UpdateUnavailable("GitHub sent something that is not JSON") from None
    tag = payload.get("tag_name")
    return tag if isinstance(tag, str) else None


def compare(installed: str, published: str | None) -> dict:
    """Reports what is true. It never says "up to date" without checking."""
    report = {"installed": installed, "published": published,
              "action": "none", "from_main": True,
              "archive": ARCHIVE_ROOT,
              "detail": ""}
    if published is None:
        report["action"] = "unknown"
        report["detail"] = (
            "No published release. Installing would fetch the head of main, "
            "which is neither versioned nor reviewed.")
        return report
    try:
        left, right = parse_version(installed), parse_version(published)
    except UpdateUnavailable as reason:
        report["action"] = "unknown"
        report["detail"] = f"{reason}."
        return report
    if left == right:
        report["action"] = "current"
        report["detail"] = "The installed version is the published one."
    elif right > left:
        report["action"] = "update"
        report["detail"] = f"{installed} is behind {published}."
    else:
        report["action"] = "ahead"
        report["detail"] = (f"{installed} is newer than the published {published}; "
                            "that is normal when installed from main.")
    return report


def fetch_checksums(url: str, opener=urllib.request.urlopen) -> dict[str, str]:
    """Reads a SHA256SUMS file. Returns name to digest."""
    request = urllib.request.Request(url, headers={"User-Agent": "cshcli"})
    try:
        with opener(request, timeout=15) as response:
            body = response.read(1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("The checksum file could not be downloaded") from None
    digests: dict[str, str] = {}
    for line in body.decode("utf-8", "replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip(), parts[1].strip().lstrip("*")
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            digests[name] = digest
    return digests


def verify(path: Path, expected: str) -> bool:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == expected.strip().lower()


def download(url: str, destination: Path, opener=urllib.request.urlopen) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "cshcli"})
    try:
        with opener(request, timeout=60) as response:
            payload = response.read(MAX_DOWNLOAD + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("The download could not be completed") from None
    if len(payload) > MAX_DOWNLOAD:
        raise UpdateUnavailable("The download is implausibly large; refusing it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def install(source: Path, expected_digest: str) -> dict:
    """Verifies before installing, and refuses to install what it cannot check.

    A wheel that fails verification is deleted rather than left next to the
    installation, because a file that looks like a package is worse than no
    file at all.
    """
    import subprocess
    import sys
    if not verify(source, expected_digest):
        source.unlink(missing_ok=True)
        raise UpdateUnavailable(
            "The checksum does not match; nothing was installed and the file was removed.")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", str(source)],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise UpdateUnavailable(f"pip refused the install: {result.stderr.strip()[-300:]}")
    return {"installed": str(source), "digest": expected_digest,
            "detail": "pip reported success."}


def current_version() -> str:
    return __version__