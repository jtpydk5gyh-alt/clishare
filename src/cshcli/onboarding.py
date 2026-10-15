"""The first run, and a place to keep a key that is not in the environment.

Two problems, and they are the reason a new person gives up before the tool
does anything.

The first is that reaching something useful takes four commands and an
environment variable. That is not documentation's fault; it is a shape
problem. `start` walks the missing pieces in order and stops when there is
nothing left to ask.

The second is where the key lives. `$env:OPENAI_API_KEY` is the obvious answer
and the wrong one: it lands in the shell history, and it is inherited by every
child process the agent spawns. `Keyring` keeps it in a file only this user can
read, under the same `.cshcli` folder the database already uses. The
environment variable still wins when it is set, because someone who exported it
knows what they are doing.

Nothing here ever prints a key. `describe` reports whether one exists, how old
it is, and which variable would carry it otherwise — never the value.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from .errors import DomainError


PROVIDER_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}


class Keyring:
    def __init__(self, root: Path, clock=time.time):
        self.path = Path(root) / "keys.json"
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}

    def _write(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def permissions_are_private(self) -> bool:
        if os.name == "nt":
            return True
        return stat.S_IMODE(self.path.stat().st_mode) == 0o600

    def set(self, provider: str, secret: str) -> dict:
        if not isinstance(provider, str) or not provider.strip():
            raise DomainError(400, "invalid_provider", "The provider must be a nonempty name.")
        if not isinstance(secret, str) or not secret.strip():
            raise DomainError(400, "empty_key", "The key is empty; nothing was stored.")
        payload = self._read()
        payload[provider] = {"secret": secret.strip(), "stored_at": self.clock()}
        self._write(payload)
        return self.describe(provider)

    def get(self, provider: str) -> str | None:
        return self._read().get(provider, {}).get("secret")

    def drop(self, provider: str) -> bool:
        payload = self._read()
        if provider not in payload:
            return False
        payload.pop(provider)
        self._write(payload)
        return True

    def resolve(self, provider: str) -> tuple[str | None, str]:
        """Returns the secret and where it came from, in that order.

        The environment wins over the file, always. A key exported on purpose
        should not be silently replaced by a stale one on disk.
        """
        variable = PROVIDER_VARIABLES.get(provider)
        if variable:
            from_environment = os.environ.get(variable)
            if from_environment and from_environment.strip():
                return from_environment.strip(), "environment"
        stored = self.get(provider)
        if stored:
            return stored, "keyring"
        return None, "missing"

    def describe(self, provider: str) -> dict:
        """Says whether a key exists and where. Never says what it is."""
        secret, source = self.resolve(provider)
        stored_at = None
        record = self._read().get(provider)
        if record is not None:
            stored_at = record.get("stored_at")
        return {"provider": provider,
                "configured": secret is not None,
                "source": source,
                "variable": PROVIDER_VARIABLES.get(provider),
                "stored_at": stored_at,
                "length": len(secret) if secret else 0,
                "path": str(self.path),
                "detail": "The value is never printed, here or anywhere else."}


def next_step(store_ready: bool, identity: bool, project: bool,
              provider: str | None, provider_ready: bool) -> dict:
    """The one question worth asking, and the honest order of them."""
    if not store_ready:
        return {"step": "serve", "question": None,
                "detail": "The coordinator is not running.",
                "do": "cshcli serve"}
    if not identity:
        return {"step": "identity", "question": "¿Cómo te llamas?",
                "detail": "Aún no hay identidad en este coordinador.",
                "do": "cshcli auth register <nombre>"}
    if not project:
        return {"step": "project", "question": "¿Cómo se llama tu proyecto?",
                "detail": "Hay identidad, pero ningún proyecto.",
                "do": "cshcli project create <nombre>"}
    if not provider_ready:
        return {"step": "provider",
                "question": f"¿Usas {provider}? Pega tu clave.",
                "detail": "Hay proyecto, pero el proveedor no tiene clave.",
                "do": f"cshcli key set {provider}"}
    return {"step": "ready", "question": None, "detail": "Todo listo.",
            "do": "cshcli project list"}