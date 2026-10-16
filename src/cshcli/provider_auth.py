from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Callable


STATE_TTL_SECONDS = 600
MINUTE = 60


class EligibilityError(Exception):
    pass


REVIEWED: dict[str, dict] = {}


class SecureStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def put(self, key: str, value: str) -> None:
        payload = self._read()
        payload[key] = value
        self._write(payload)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def drop(self, key: str) -> bool:
        payload = self._read()
        if key not in payload:
            return False
        payload.pop(key)
        self._write(payload)
        return True

    def keys(self) -> list[str]:
        return sorted(self._read())


def _verifier() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class ProviderAuth:
    def __init__(self, store: SecureStore, *, reviewed: dict[str, dict] | None = None,
                 transport: Callable[[str, dict], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.reviewed = dict(REVIEWED if reviewed is None else reviewed)
        self.transport = transport
        self.clock = clock

    def capabilities(self, provider: str, mode: str, model: str | None = None,
                     cli_version: str | None = None) -> dict:
        record = self.reviewed.get(provider)
        if record is None:
            return {"provider": provider, "mode": mode, "native_login": False,
                    "reason": "not_reviewed",
                    "detail": "No documented authorisation for native login was reviewed "
                              "for this provider; the official adapter is kept.",
                    "official_adapter": record_official_adapter(provider),
                    "reviewed_on": None}
        return {"provider": provider, "mode": mode, "native_login": True,
                "reason": "reviewed", "reviewed_on": record.get("reviewed_on"),
                "scopes": list(record.get("scopes", [])),
                "modality": record.get("modality"),
                "restrictions": list(record.get("restrictions", [])),
                "official_adapter": record_official_adapter(provider)}

    def begin(self, provider: str, redirect_uri: str) -> dict:
        record = self.reviewed.get(provider)
        if record is None:
            raise EligibilityError(
                f"native_login is not enabled for {provider}: no documented authorisation "
                "has been reviewed. Use the official adapter.")
        if self.transport is None:
            raise EligibilityError("no transport is configured for the token exchange")
        uri = _redirect(redirect_uri)
        state = secrets.token_urlsafe(32)
        verifier, challenge = _verifier()
        pending = self.store.get("pending") or "{}"
        try:
            waiting = json.loads(pending)
        except ValueError:
            waiting = {}
        waiting[state] = {"provider": provider, "redirect_uri": uri,
                          "verifier": verifier, "code_challenge": challenge,
                          "expires_at": self.clock() + STATE_TTL_SECONDS}
        self.store.put("pending", json.dumps(waiting))
        url = (f"{record['authorize_url']}?response_type=code"
               f"&client_id={record['client_id']}&redirect_uri={uri}"
               f"&state={state}&code_challenge={challenge}"
               f"&code_challenge_method=S256"
               f"&scope={record.get('scope', '')}")
        return {"provider": provider, "authorization_url": url, "state": state,
                "redirect_uri": uri, "expires_in": STATE_TTL_SECONDS,
                "pkce": "S256", "flow": "authorization_code"}

    def finish(self, provider: str, code: str, state: str) -> dict:
        pending = json.loads(self.store.get("pending") or "{}")
        entry = pending.pop(state, None)
        self.store.put("pending", json.dumps(pending))
        if entry is None:
            raise EligibilityError("That state is unknown, already used or expired.")
        if entry["expires_at"] <= self.clock():
            raise EligibilityError("That state expired before it was used.")
        if entry["provider"] != provider:
            raise EligibilityError("That state belongs to another provider.")
        if not isinstance(code, str) or not code.strip():
            raise EligibilityError("The authorization code is missing.")
        answer = self.transport(provider, {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": entry["redirect_uri"],
            "code_verifier": entry["verifier"],
            "client_id": self.reviewed[provider]["client_id"],
        })
        access = answer.get("access_token")
        if not isinstance(access, str) or not access:
            raise EligibilityError("The provider did not return an access token.")
        account = answer.get("account") or {}
        record = {
            "provider": provider,
            "account_id": answer.get("account_id", provider),
            "account_name": account.get("name"),
            "billing_modality": account.get("billing", "unknown"),
            "data_destination": account.get("data_destination", "not stated by the provider"),
            "scopes": list(self.reviewed[provider].get("scopes", [])),
            "obtained_at": self.clock(),
        }
        self.store.put(f"provider:{provider}", access)
        self.store.put(f"account:{provider}", json.dumps(record))
        return {"provider": provider, "account": record,
                "coordinator_told": False,
                "detail": "The exchange and the token stayed on this machine."}

    def account(self, provider: str) -> dict | None:
        raw = self.store.get(f"account:{provider}")
        return json.loads(raw) if raw else None

    def revoke(self, provider: str, account_id: str) -> None:
        record = self.account(provider)
        if record is None or record["account_id"] != account_id:
            raise EligibilityError("No stored account matches that identifier.")
        self.store.drop(f"provider:{provider}")
        self.store.drop(f"account:{provider}")


def record_official_adapter(provider: str) -> dict:
    return {
        "openai": {"kind": "api_key_and_official_cli", "variable": "OPENAI_API_KEY"},
        "anthropic": {"kind": "api_key_and_official_cli", "variable": "ANTHROPIC_API_KEY"},
        "google": {"kind": "api_key", "variable": "GEMINI_API_KEY"},
        "minimax": {"kind": "api_key", "variable": "MINIMAX_API_KEY"},
        "codex": {"kind": "official_cli", "variable": None},
        "claude-code": {"kind": "official_cli", "variable": None},
        "gemini-cli": {"kind": "official_cli", "variable": None},
    }.get(provider, {"kind": "unknown", "variable": None})


def _redirect(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(("http://127.0.0.1", "http://localhost")):
        raise EligibilityError("The redirect must be a loopback address.")
    if "#" in value or "state" in value or "code" in value:
        raise EligibilityError("The redirect must be bare; the code arrives in the query.")
    if len(value) > 512:
        raise EligibilityError("The redirect is too long.")
    return value


def redact(value: str) -> str:
    return f"({len(value)} caracteres)"