from __future__ import annotations

import os
import time
from typing import Callable

from . import providers
from .errors import DomainError

_SECRET_PREFIXES = ("CSHCLI_", "OPENAI_", "ANTHROPIC_", "GEMINI_")
_INHERITED_VARIABLES = ("PATH",)


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return any(upper.startswith(prefix) for prefix in _SECRET_PREFIXES)


def _mode(provider: str) -> str:
    if provider in getattr(providers, "_API_KEYS", {}):
        return "api"
    if provider in getattr(providers, "_BINARIES", {}):
        return "cli"
    return "api"


def _capability_record(provider: str, model: str | None) -> dict:
    function = getattr(providers, "capabilities", None)
    if function is None:
        return {}
    record = function(provider, _mode(provider), model)
    if not isinstance(record, dict):
        return {}
    if record.get("text") == "unknown" and not any(
            record.get(field) is True for field in ("configured", "verified", "native_login")):
        raise DomainError(400, "invalid_provider", f"El proveedor {provider} no admite el modo texto mediado.")
    return record


class Broker:
    def __init__(self, provider_callable: Callable[..., str] | None = None,
                 clock: Callable[[], float] = time.time):
        self._provider_callable = provider_callable
        self._clock = clock

    def generate(self, run_id: str, provider: str, model: str | None,
                 context_manifest: dict, prompt: str | None = None) -> dict:
        if not isinstance(provider, str) or not provider.strip():
            raise DomainError(400, "invalid_provider", "Indica el proveedor de texto mediado.")
        if provider == "codex":
            raise DomainError(400, "provider_isolation_unverified",
                              "El broker no envía contexto compartido a un CLI que puede leer el equipo. Usa una API o Claude CLI con herramientas desactivadas.")
        capabilities = _capability_record(provider, model)
        question = self._question(context_manifest, prompt)
        call = self._provider_callable if self._provider_callable is not None else providers.chat
        return {"run_id": run_id, "provider": provider, "model": model, "text": call(provider, model, question),
                "capabilities": capabilities, "generated_at": self._clock()}

    def _question(self, context_manifest: dict, prompt: str | None) -> str:
        if isinstance(prompt, str) and prompt.strip():
            return prompt
        entries = context_manifest.get("entries") if isinstance(context_manifest, dict) else None
        if not isinstance(entries, list) or not entries:
            raise DomainError(400, "invalid_manifest", "El manifiesto de contexto no trae entradas utilizables.")
        blocks = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise DomainError(400, "invalid_manifest", "El manifiesto de contexto no trae entradas utilizables.")
            blocks.append(f"{entry.get('key') or ''}\n{entry.get('content') or ''}")
        return "\n".join(blocks)

    def child_environment(self, run_id: str, scope: str) -> dict:
        environment = {}
        for name in _INHERITED_VARIABLES:
            value = os.environ.get(name)
            if value is not None and not _is_secret(name):
                environment[name] = value
        environment["CSHCLI_RUN_ID"] = str(run_id)
        environment["CSHCLI_RUN_SCOPE"] = str(scope)
        return environment

    @staticmethod
    def assert_no_secrets(environment: dict, secrets: list[str]) -> None:
        for name, value in environment.items():
            text = value if isinstance(value, str) else str(value)
            for secret in secrets or ():
                if isinstance(secret, str) and secret and secret in text:
                    raise DomainError(500, "secret_leak", f"El entorno hijo expone un secreto en {name}.")