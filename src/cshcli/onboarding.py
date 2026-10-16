from __future__ import annotations

import getpass
import json
import os
import stat
import sys
import time
from pathlib import Path

from . import __version__
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


MENU = (
    "  1) Sesión           Trabaja por tu cuenta\n"
    "  2) Unirme o crear   Un proyecto compartido con otra persona\n"
)


def _ask(prompt, reader, out):
    while True:
        try:
            answer = reader(prompt)
        except EOFError:
            raise DomainError(400, "input_required",
                              "cshcli start necesita una terminal interactiva.") from None
        answer = (answer or "").strip()
        if answer:
            return answer
        out("  No puede estar vacío.")


def _ask_default(prompt, default, reader):
    try:
        answer = reader(prompt)
    except EOFError:
        raise DomainError(400, "input_required",
                          "cshcli start necesita una terminal interactiva.") from None
    return (answer or "").strip() or default


def _pick(prompt, options, reader, out):
    while True:
        answer = _ask(prompt, reader, out)
        if answer in options:
            return answer
        out("  Opciones: " + ", ".join(sorted(options)) + ".")


def _confirm(prompt, reader, out):
    while True:
        answer = _ask(prompt, reader, out).lower()
        if answer in {"s", "si", "sí", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        out("  Responde s o n.")


def _remember(session, project):
    session.remember(project=project["id"], project_name=project["name"])


def _known_project(client, project_id):
    for project in client.request("GET", "/v1/projects"):
        if project["id"] == project_id:
            return project
    return {"id": project_id, "name": project_id}


def _new_project(client, reader, out):
    name = _ask_default("  ¿Cómo se llama tu proyecto? [demo] ", "demo", reader)
    project = client.request("POST", "/v1/projects", {"name": name})
    out(f"  Proyecto '{project['name']}' creado.")
    return project


def _shared(client, session, reader, secret, out):
    if not _confirm("  ¿Tienes un código de invitación? [s/n] ", reader, out):
        project = _new_project(client, reader, out)
        invite = client.request("POST", f"/v1/projects/{project['id']}/invites",
                                {"role": "member", "ttl": 604800})
        _remember(session, project)
        out("\n  Para invitar a alguien, dale este código:\n")
        out(f"    {invite['token']}\n")
        return project
    code = secret("  Pega el código: ")
    accepted = client.request("POST", "/v1/invites/accept", {"token": code})
    project = _known_project(client, accepted["project_id"])
    _remember(session, project)
    out(f"\n  Te uniste a '{project['name']}' como {accepted['role']}.")
    return project


def _provider_setup(session, keyring, reader, secret, out):
    known = sorted(name for name in PROVIDER_VARIABLES if keyring.resolve(name)[0])
    if known and not session.provider:
        session.remember(provider=known[0])
    if session.provider:
        out(f"  Proveedor: {session.provider}.")
        return
    provider = _pick(f"  ¿Qué proveedor usas? ({'/'.join(sorted(PROVIDER_VARIABLES))}) ",
                     set(PROVIDER_VARIABLES), reader, out)
    while not keyring.resolve(provider)[0]:
        value = secret(f"  Clave de {provider} (no se muestra): ")
        if (value or "").strip():
            keyring.set(provider, value)
            out(f"  Clave guardada en {keyring.path}")
            break
        out("  La clave llegó vacía; inténtalo otra vez.")
    session.remember(provider=provider)


def run_loop(provider, model, ask, reader=None, out=None):
    reader = reader or input
    out = out or print
    while True:
        try:
            line = reader("> ")
        except EOFError:
            out("")
            return 0
        line = (line or "").strip()
        if not line:
            continue
        if line in {"/exit", "/quit", "/salir"}:
            return 0
        try:
            out(ask(provider, model, line))
        except DomainError as error:
            out(f"[{error.code}] {error}")


def run_wizard(client, session, keyring, reader=None, secret=None, out=None):
    reader = reader or input
    out = out or print
    secret = secret or (lambda prompt: getpass.getpass(prompt, stream=sys.stderr))
    if session.ready():
        out(f"\n  Ya estás listo: {session.name} en '{session.project_name}'.")
        out("  Escribe 'cshcli' para hablar con tu agente.\n")
        return 0
    out(f"\n  CSHCLI {__version__} — coordinas agentes con tus propias cuentas\n")
    out(MENU)
    route = _pick("\n  Elige 1 o 2: ", {"1", "2"}, reader, out)
    name = session.name or _ask("  ¿Cómo te llamas? ", reader, out)
    identity = client.request("POST", "/v1/users", {"name": name})
    client.token = identity["token"]
    session.remember(name=name, token=identity["token"])
    out(f"\n  Hola, {name}.")
    if route == "1":
        _remember(session, _new_project(client, reader, out))
    else:
        _shared(client, session, reader, secret, out)
    _provider_setup(session, keyring, reader, secret, out)
    out(f"\n  Listo. Escribe 'cshcli' para hablar con tu agente en "
        f"'{session.project_name}'.\n")
    return 0


def next_step(store_ready: bool, identity: bool, project: bool,
              provider: str | None, provider_ready: bool) -> dict:
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