from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .context import ContextAssembler
from .errors import DomainError
from .integration import IntegrationGate
from .policy import Policy
from .store import SCHEMA_VERSION, Store

MAX_BODY = 1024 * 1024


class Coordinator(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, store):
        self.store = store
        self.started_at = time.time()
        self._requests_served = 0
        self._requests_lock = Lock()
        super().__init__(address, Handler)

    def count_request(self):
        with self._requests_lock:
            self._requests_served += 1

    def health(self) -> dict:
        database, schema = self._probe()
        with self._requests_lock:
            requests_served = self._requests_served
        return {
            "status": "ok" if database == "ok" else "degraded",
            "mode": "local-pilot",
            "database": database,
            "schema_version": schema,
            "version": __version__,
            "protocol": "v1",
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "requests_served": requests_served,
        }

    def _probe(self) -> tuple[str, int]:
        try:
            if not self.store.ping():
                return "unavailable", 0
            schema = self.store.schema_version()
            return ("ok" if schema == SCHEMA_VERSION else "unavailable"), schema
        except Exception:
            return "unavailable", 0


class Handler(BaseHTTPRequestHandler):
    server_version = "CSHCLI/0.1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        pass

    def parse_request(self):
        valid = super().parse_request()
        if valid:
            self.server.count_request()
        return valid

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        if self.headers.get("Transfer-Encoding"):
            raise DomainError(400, "invalid_body", "Transfer-Encoding no está permitido.")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise DomainError(400, "invalid_body", "Content-Length duplicado.")
        try:
            size = int(lengths[0]) if lengths else 0
        except ValueError:
            raise DomainError(400, "invalid_body", "Content-Length inválido.") from None
        if size < 0 or size > MAX_BODY:
            raise DomainError(413, "body_too_large", "El límite de la petición es 1 MiB.")
        if size == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise DomainError(415, "json_required", "Usa Content-Type: application/json.")
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("truncated")
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise DomainError(400, "invalid_json", "El cuerpo debe ser un objeto JSON válido.") from None
        if not isinstance(payload, dict):
            raise DomainError(400, "invalid_json", "El cuerpo debe ser un objeto JSON.")
        return payload

    def _handle(self, method):
        try:
            try:
                authority = urlsplit("http://" + self.headers.get("Host", ""))
                valid_host = authority.hostname in {"localhost", "127.0.0.1"} and authority.port == self.server.server_port and not authority.username and not authority.password
            except ValueError:
                valid_host = False
            if not valid_host:
                raise DomainError(403, "invalid_host", "Este coordinador solo admite clientes locales.")
            if self.headers.get("Origin") is not None:
                raise DomainError(403, "browser_request", "Usa el CLI local para acceder al coordinador.")
            try:
                parsed_url = urlsplit(self.path)
                query = parse_qs(parsed_url.query, keep_blank_values=True, max_num_fields=10)
            except ValueError:
                raise DomainError(400, "invalid_query", "La URL o sus parámetros no son válidos; usa como máximo 10 campos.") from None
            path = [unquote(piece) for piece in parsed_url.path.strip("/").split("/")]
            if method == "GET" and path == ["health"]:
                self._json(200, {"data": self.server.health()})
                return
            store = self.server.store
            if method == "POST" and path == ["v1", "users"]:
                body = self._body()
                result = store.register_user(required(body, "name"))
                self._json(201, {"data": result})
                return
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or not auth[7:].strip():
                raise DomainError(401, "authentication_required", "Falta CSHCLI_TOKEN o un bearer válido.")
            user = store.authenticate(auth[7:])
            body = self._body() if method in {"POST", "PUT", "DELETE"} else {}
            status, result = self._dispatch(store, user, method, path, body, query)
            self._json(status, {"data": result})
        except DomainError as error:
            self.close_connection = True
            self._json(error.status, {"error": {"code": error.code, "message": error.message}})
        except (TimeoutError, ConnectionError, BrokenPipeError):
            self.close_connection = True
        except Exception:
            self.close_connection = True
            self._json(500, {"error": {"code": "internal_error", "message": "Error interno del coordinador."}})

    def _dispatch(self, store, user, method, path, body, query):
        if path == ["v1", "projects"]:
            if method == "GET":
                return 200, store.list_projects(user)
            if method == "POST":
                return 201, store.create_project(user, required(body, "name"))
        if path == ["v1", "invites", "accept"] and method == "POST":
            return 200, store.accept_invite(user, required(body, "token"))
        if len(path) >= 4 and path[:2] == ["v1", "projects"]:
            project, resource = path[2], path[3]
            if len(path) == 4:
                if resource == "invites" and method == "POST":
                    return 201, store.create_invite(user, project, body.get("role", "member"), body.get("ttl", 3600))
                if resource == "memory":
                    if method == "GET":
                        if any(key not in {"limit", "after"} or len(value) != 1 for key, value in query.items()):
                            raise DomainError(400, "invalid_query", "Usa limit y after una sola vez.")
                        try:
                            limit = int(query.get("limit", ["10"])[0])
                        except ValueError:
                            raise DomainError(400, "invalid_query", "limit debe ser un entero de 1 a 10.") from None
                        return 200, store.list_memory_page(user, project, limit, query.get("after", [None])[0])
                    if method == "PUT":
                        return 200, store.put_memory(user, project, required(body, "key"), required(body, "content"), required(body, "expected_version"))
                if resource == "leases":
                    if method == "GET":
                        return 200, store.list_leases(user, project)
                    if method == "POST":
                        return 201, store.acquire_leases(user, project, required(body, "agent_id"), required(body, "resources"), body.get("ttl", 120))
                if resource == "events" and method == "GET":
                    return 200, store.list_events(user, project)
                if resource == "context" and method == "POST":
                    return 200, ContextAssembler(store).build(
                        user, project, required(body, "task_id"),
                        _text(body, "base_sha"), _budget(body),
                        body.get("after_revision"))
                if resource == "runs":
                    if method == "POST":
                        return 201, Policy(store).reserve_run(
                            user, project, required(body, "run_id"),
                            _integer(body, "authorization_generation"),
                            body.get("limits", {}))
                    if method == "GET":
                        return 200, Policy(store).active_runs(user, project)
                if resource == "patches" and method == "GET":
                    return 200, IntegrationGate(store).list_accepted(
                        user, project, _limit(query))
            if resource == "runs" and len(path) == 5 and path[4] == "settle" and method == "POST":
                return 200, Policy(store).finish_run(
                    user, project, required(body, "run_id"),
                    required(body, "attempt_id"), required(body, "measured_usage"))
            if resource == "patches" and len(path) == 5 and path[4] == "accept" and method == "POST":
                return 200, IntegrationGate(store).accept_patch(
                    user, project, required(body, "run_id"),
                    _integer(body, "authorization_generation"),
                    required(body, "lease_fences"), _text(body, "base_sha"),
                    _text(body, "commit_sha"), body.get("resources"))
            if resource == "leases" and len(path) in {5, 6}:
                lease_id = path[4]
                if len(path) == 6 and path[5] == "renew" and method == "POST":
                    return 200, store.renew_lease(user, project, lease_id, required(body, "fence"), body.get("ttl", 120))
                if len(path) == 5 and method == "DELETE":
                    return 200, store.release_lease(user, project, lease_id, required(body, "fence"))
        raise DomainError(404, "route_not_found", "Ruta o método no disponible.")


def required(body, key):
    if key not in body:
        raise DomainError(400, "missing_field", f"Falta el campo {key}.")
    return body[key]


def _text(body, key):
    value = required(body, key)
    if not isinstance(value, str):
        raise DomainError(400, "invalid_field", f"{key} debe ser texto.")
    return value


def _integer(body, key):
    value = required(body, key)
    if type(value) is not int:
        raise DomainError(400, "invalid_field", f"{key} debe ser un entero.")
    return value


def _budget(body):
    value = body.get("context_budget_bytes", 65536)
    if type(value) is not int or value < 0:
        raise DomainError(400, "invalid_field", "context_budget_bytes debe ser un entero no negativo.")
    return value


def _limit(query):
    if any(key != "limit" or len(value) != 1 for key, value in query.items()):
        raise DomainError(400, "invalid_query", "Usa limit una sola vez.")
    try:
        return int(query.get("limit", ["10"])[0])
    except ValueError:
        raise DomainError(400, "invalid_query", "limit debe ser un entero.") from None


def make_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> Coordinator:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("El servidor piloto solo admite 127.0.0.1 o localhost; usa un gateway para producción.")
    return Coordinator((host, port), Store(db_path))
