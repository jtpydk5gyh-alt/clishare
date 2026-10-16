from __future__ import annotations

import json
import os
import stat
from pathlib import Path


class Session:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "session.json"

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def _field(self, name):
        value = self._read().get(name)
        return value if isinstance(value, str) and value else None

    @property
    def name(self):
        return self._field("name")

    @property
    def token(self):
        return self._field("token")

    @property
    def project(self):
        return self._field("project")

    @property
    def project_name(self):
        return self._field("project_name")

    def remember(self, name=None, token=None, project=None, project_name=None):
        payload = self._read()
        for key, value in (("name", name), ("token", token),
                           ("project", project), ("project_name", project_name)):
            if value is not None:
                payload[key] = value
        self._write(payload)
        return payload

    def forget(self):
        try:
            self.path.unlink()
        except OSError:
            return False
        return True

    def ready(self) -> bool:
        return bool(self.token and self.project)