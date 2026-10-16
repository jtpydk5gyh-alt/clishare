from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import DomainError

_API_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
             "google": "GEMINI_API_KEY", "minimax": "MINIMAX_API_KEY"}
_BINARIES = {"codex": "codex", "claude-code": "claude", "gemini-cli": "gemini"}
_API_TIMEOUT = 60
_CLI_TIMEOUT = 300
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MINIMAX_BASE = "https://api.minimax.io/v1"


class _NoRedirect(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect())


def _redact(text: str) -> str:
    for name in _API_KEYS.values():
        key = os.environ.get(name)
        if key:
            text = text.replace(key, "[REDACTED]")
    return text


def status() -> list[dict]:
    rows = [{"provider": provider, "mode": "api-key", "configured": bool(os.environ.get(variable)),
             "environment_variable": variable}
            for provider, variable in _API_KEYS.items()]
    rows.extend({"provider": provider, "mode": "official-cli", "installed": shutil.which(binary) is not None,
                 "authentication": "managed-by-official-cli", "authentication_verified": False,
                 "text_chat_available": provider != "gemini-cli",
                 "warning": "No se ha verificado ninguna cuenta autenticada. La facturación depende de las credenciales propias del CLI oficial."}
                for provider, binary in _BINARIES.items())
    return rows


def _executable(binary: str) -> str:
    executable = shutil.which(binary)
    if executable is None:
        raise DomainError(400, "cli_not_installed", f"Instala el CLI oficial {binary} y añádelo al PATH.")
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        raise DomainError(400, "cli_native_required", f"Usa el ejecutable nativo de {binary}, no un wrapper .cmd/.bat.")
    return executable


def login(provider: str) -> int:
    commands = {"codex": ("codex", ["login"]), "claude": ("claude", ["auth", "login"]),
                "gemini": ("gemini", [])}
    if provider not in commands:
        raise DomainError(400, "provider_unknown", "Login admite codex, claude o gemini.")
    binary, arguments = commands[provider]
    try:
        return subprocess.run([_executable(binary), *arguments], shell=False, check=False,
                              env=_cli_environment()).returncode
    except OSError:
        raise DomainError(400, "cli_start_failed", "No se pudo iniciar el CLI oficial.") from None


def chat(provider: str, model: str | None, prompt: str, history=None) -> str:
    if provider not in _API_KEYS and provider not in _BINARIES:
        raise DomainError(400, "provider_unknown", "Proveedor no compatible.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise DomainError(400, "prompt_required", "Escribe un prompt no vacío.")
    if model is not None and (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)):
        raise DomainError(400, "model_invalid", "El identificador de modelo no es válido.")
    if provider in _API_KEYS:
        if model is None:
            raise DomainError(400, "model_required", "Selecciona un modelo explícito con --model para usar una API.")
        key = os.environ.get(_API_KEYS[provider], "")
        if not key.strip():
            raise DomainError(400, "api_key_missing", f"Configura {_API_KEYS[provider]} en tu entorno local.")
        if "\r" in key or "\n" in key:
            raise DomainError(400, "api_key_invalid", "La API key contiene caracteres no válidos.")
        return _redact(_api_chat(provider, model, prompt, key, history))
    if provider == "gemini-cli":
        raise DomainError(400, "text_mode_unavailable",
                          "El chat Gemini CLI está pendiente de aislamiento verificable. Usa google con GEMINI_API_KEY y --model.")
    return _redact(_cli_chat(provider, model, prompt))


def _request(url: str, payload: dict, headers: dict) -> dict:
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with _OPENER.open(request, timeout=_API_TIMEOUT) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise DomainError(502, "provider_response_invalid", "La respuesta del proveedor supera el tamaño permitido.")
        parsed = json.loads(raw)
    except HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise DomainError(401, "provider_auth_failed", "El proveedor rechazó la autenticación. Revisa tu API key y permisos.") from None
        if code == 429:
            raise DomainError(429, "provider_rate_limited", "El proveedor agotó la cuota o limitó las solicitudes.") from None
        raise DomainError(502, "provider_http_error", f"El proveedor rechazó la solicitud (HTTP {code}).") from None
    except (TimeoutError, subprocess.TimeoutExpired):
        raise DomainError(504, "provider_timeout", "El proveedor no respondió dentro del tiempo permitido.") from None
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise DomainError(504, "provider_timeout", "El proveedor no respondió dentro del tiempo permitido.") from None
        raise DomainError(502, "provider_unavailable", "No se pudo conectar con el proveedor.") from None
    except OSError:
        raise DomainError(502, "provider_unavailable", "No se pudo conectar con el proveedor.") from None
    except (ValueError, UnicodeError):
        raise DomainError(502, "provider_response_invalid", "El proveedor devolvió una respuesta no válida.") from None
    if not isinstance(parsed, dict):
        raise DomainError(502, "provider_response_invalid", "El proveedor devolvió una respuesta no válida.")
    return parsed


def _messages(history, prompt: str) -> list[dict]:
    turns = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            turns.append({"role": role, "content": content})
    turns.append({"role": "user", "content": prompt})
    return turns


def _api_chat(provider: str, model: str, prompt: str, key: str, history=None) -> str:
    turns = _messages(history, prompt)
    carried = len(turns) > 1
    if provider == "openai":
        body = ({"model": model, "input": prompt, "store": False} if not carried else
                {"model": model, "store": False, "input": [
                    {"role": turn["role"],
                     "content": [{"type": "output_text" if turn["role"] == "assistant"
                                  else "input_text", "text": turn["content"]}]}
                    for turn in turns]})
        response = _request("https://api.openai.com/v1/responses", body,
                            {"Authorization": f"Bearer {key}"})
        if response.get("status") != "completed":
            raise DomainError(502, "provider_response_incomplete", "El proveedor no completó la respuesta.")
        messages = _list(response.get("output"))
        blocks = [part for item in messages if isinstance(item, dict) and item.get("type") == "message"
                  for part in _list(item.get("content"))]
        text = _text(blocks, "output_text")
    elif provider == "anthropic":
        response = _request("https://api.anthropic.com/v1/messages",
                            {"model": model, "max_tokens": 4096, "messages": turns},
                            {"x-api-key": key, "anthropic-version": "2023-06-01"})
        if response.get("stop_reason") != "end_turn":
            raise DomainError(502, "provider_response_incomplete", "El proveedor no completó una respuesta de texto.")
        text = _text(_list(response.get("content")), "text")
    elif provider == "google":
        model_name = model.removeprefix("models/")
        response = _request("https://generativelanguage.googleapis.com/v1beta/models/" + quote(model_name, safe="") + ":generateContent",
                            {"contents": [{"role": "model" if turn["role"] == "assistant" else "user",
                                           "parts": [{"text": turn["content"]}]} for turn in turns]},
                            {"x-goog-api-key": key})
        candidates = _list(response.get("candidates"))
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        if candidate.get("finishReason") != "STOP":
            raise DomainError(502, "provider_response_incomplete", "El proveedor no completó una respuesta de texto.")
        content = candidate.get("content", {})
        text = _text(_list(content.get("parts")) if isinstance(content, dict) else [])
    else:
        response = _request(_MINIMAX_BASE + "/chat/completions",
                            {"model": model, "messages": turns,
                             "max_completion_tokens": 4096},
                            {"Authorization": f"Bearer {key}"})
        choices = _list(response.get("choices"))
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        if choice.get("finish_reason") != "stop":
            raise DomainError(502, "provider_response_incomplete", "El proveedor no completó una respuesta de texto.")
        message = choice.get("message", {})
        text = message.get("content") if isinstance(message, dict) else None
        text = text if isinstance(text, str) else ""
    if not text.strip():
        raise DomainError(502, "provider_response_empty", "El proveedor no devolvió texto.")
    return text


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _text(blocks: list, kind: str | None = None) -> str:
    return "\n".join(block["text"] for block in blocks if isinstance(block, dict)
                     and isinstance(block.get("text"), str) and not block.get("thought")
                     and (kind is None or block.get("type") == kind))


def _cli_environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items()
            if name.upper() not in _API_KEYS.values() and not name.upper().startswith("CSHCLI_")}


def _stop_process(process) -> None:
    try:
        if os.name == "nt":
            if process.poll() is None:
                taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], shell=False,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, check=False, env=_cli_environment())
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _run_capture(arguments: list[str], *, prompt: str | None = None, timeout: int = _CLI_TIMEOUT,
                 cwd: str | None = None):
    buffers = [bytearray(), bytearray()]
    overflow, failed, lock = threading.Event(), threading.Event(), threading.Lock()

    def collect(stream, buffer):
        try:
            with stream:
                while chunk := stream.read1(65536):
                    with lock:
                        if sum(map(len, buffers)) + len(chunk) > _MAX_RESPONSE_BYTES:
                            overflow.set()
                            return
                        buffer.extend(chunk)
        except OSError:
            failed.set()

    try:
        with tempfile.TemporaryFile() as input_stream:
            input_stream.write((prompt or "").encode("utf-8"))
            input_stream.seek(0)
            process = subprocess.Popen(arguments, stdin=input_stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       shell=False, cwd=cwd, env=_cli_environment(), start_new_session=os.name != "nt")
            readers = [threading.Thread(target=collect, args=(stream, buffer), daemon=True)
                       for stream, buffer in zip((process.stdout, process.stderr), buffers)]
            for reader in readers:
                reader.start()
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if overflow.is_set():
                        raise DomainError(502, "provider_response_invalid", "La salida del CLI supera el tamaño permitido.")
                    if failed.is_set():
                        raise DomainError(502, "provider_cli_failed", "No se pudo leer la salida del CLI.")
                    if process.poll() is not None and not any(reader.is_alive() for reader in readers):
                        break
                    if time.monotonic() >= deadline:
                        raise DomainError(504, "provider_timeout", "El CLI superó el tiempo permitido.")
                    time.sleep(.01)
            finally:
                _stop_process(process)
                for reader in readers:
                    reader.join(timeout=.1)
    except subprocess.TimeoutExpired:
        raise DomainError(504, "provider_timeout", "El CLI superó el tiempo permitido.") from None
    except OSError:
        raise DomainError(400, "cli_start_failed", "No se pudo iniciar el CLI oficial.") from None
    if process.returncode != 0:
        raise DomainError(502, "provider_cli_failed", "El CLI oficial falló. Comprueba su versión, login y cuota directamente.")
    return subprocess.CompletedProcess(arguments, process.returncode,
                                       *(bytes(buffer).decode("utf-8", errors="replace") for buffer in buffers))


def _cli_chat(provider: str, model: str | None, prompt: str) -> str:
    executable = _executable(_BINARIES[provider])
    help_args = [executable, "exec", "--help"] if provider == "codex" else [executable, "--help"]
    help_text = _run_capture(help_args, timeout=10).stdout
    if provider == "codex":
        required = ("--sandbox", "read-only", "--json", "--ephemeral", "--ignore-user-config")
        arguments = [executable, "exec", "--sandbox", "read-only", "--json", "--ephemeral", "--ignore-user-config",
                     "--skip-git-repo-check"]
    else:
        required = ("--tools", "--disallowedTools", "--safe-mode", "--no-session-persistence", "--output-format")
        arguments = [executable, "-p", "--tools", "", "--disallowedTools", "mcp__*", "--safe-mode",
                     "--no-session-persistence", "--output-format", "text", "--settings", '{"disableAllHooks":true}']
    if any(flag not in help_text for flag in required):
        raise DomainError(400, "cli_version_unsupported", "Actualiza el CLI oficial: faltan opciones necesarias para el modo de texto seguro.")
    if model is not None:
        arguments.extend(["--model", model])
    if provider == "codex":
        arguments.append("-")
    with tempfile.TemporaryDirectory(prefix="cshcli-chat-") as working_directory:
        output = _run_capture(arguments, prompt=prompt, cwd=working_directory).stdout
    if provider == "claude-code":
        if not output.strip():
            raise DomainError(502, "provider_response_empty", "El CLI no devolvió texto.")
        return output.strip()
    messages, completed = [], False
    try:
        for line in output.splitlines():
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError
            if event.get("type") in ("error", "turn.failed"):
                raise DomainError(502, "provider_cli_failed", "El CLI no completó la solicitud.")
            if event.get("type") == "turn.completed":
                completed = True
            item = event.get("item", {})
            if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                if isinstance(item.get("text"), str):
                    messages.append(item["text"])
    except (ValueError, UnicodeError):
        raise DomainError(502, "provider_response_invalid", "El CLI devolvió una respuesta no válida.") from None
    if not completed or not messages:
        raise DomainError(502, "provider_response_incomplete", "El CLI no completó una respuesta de texto.")
    return "\n".join(messages)


_CAPABILITY_FIELDS = (
    "configured", "verified", "text", "tools_mediable", "sandbox", "streaming",
    "context_limit", "output_limit", "usage_available", "price_available",
    "native_login", "requires_flags",
)
_API_ENDPOINTS = {"openai": "https://api.openai.com/v1/responses",
                  "anthropic": "https://api.anthropic.com/v1/messages",
                  "google": "https://generativelanguage.googleapis.com/v1beta/models",
                  "minimax": _MINIMAX_BASE + "/chat/completions"}
_CLI_FLAG_CANDIDATES = {"codex": ("--sandbox", "--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check"),
                        "claude-code": ("--tools", "--disallowedTools", "--safe-mode", "--no-session-persistence", "--output-format"),
                        "gemini-cli": ()}
_CLI_HELP_TIMEOUT = 10


def _unknown_capabilities() -> dict:
    values: dict = {field: "unknown" for field in _CAPABILITY_FIELDS}
    values["configured"] = False
    values["verified"] = False
    return values


def _unverified_cli_capabilities() -> dict:
    values = _unknown_capabilities()
    values["native_login"] = True
    values["requires_flags"] = []
    return values


def _cli_sandbox(provider: str, help_text: str) -> str | None:
    if provider == "codex" and "--sandbox" in help_text and "read-only" in help_text:
        return "read-only"
    if provider == "claude-code" and "--safe-mode" in help_text:
        return "safe-mode"
    return "unknown"


def _api_capabilities(provider: str, model: str | None) -> dict:
    configured = bool(os.environ.get(_API_KEYS[provider]))
    values = _unknown_capabilities()
    values.update({"configured": configured, "verified": configured and bool(model and model.strip()),
                   "text": True, "tools_mediable": False, "sandbox": None, "streaming": True,
                   "native_login": False, "requires_flags": [], "endpoint_hint": _API_ENDPOINTS[provider]})
    return values


def _cli_capabilities(provider: str) -> dict:
    values = _unverified_cli_capabilities()
    executable = shutil.which(_BINARIES[provider])
    if executable is None:
        return values
    arguments = [executable, "exec", "--help"] if provider == "codex" else [executable, "--help"]
    try:
        help_text = _run_capture(arguments, timeout=_CLI_HELP_TIMEOUT).stdout or ""
    except DomainError:
        return values
    values.update({"configured": True, "verified": True, "sandbox": _cli_sandbox(provider, help_text),
                   "requires_flags": [flag for flag in _CLI_FLAG_CANDIDATES[provider] if flag in help_text]})
    return values


def capabilities(provider: str, mode: str, model: str | None = None, cli_version: str | None = None) -> dict:
    if mode == "api" and provider in _API_KEYS:
        return _api_capabilities(provider, model)
    if mode == "cli" and provider in _BINARIES:
        return _cli_capabilities(provider)
    return _unknown_capabilities()
