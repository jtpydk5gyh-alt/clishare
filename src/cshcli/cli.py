import argparse
import getpass
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

from . import __version__, providers
from .client import Client
from .errors import DomainError
from .onboarding import PROVIDER_VARIABLES, Keyring, next_step
from .server import make_server


def parser():
    root = argparse.ArgumentParser(prog="cshcli", description="IA personal y coordinación compartida de proyectos (piloto local).")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--url", default=os.environ.get("CSHCLI_URL", "http://127.0.0.1:8765"), help="URL base del coordinador, o CSHCLI_URL")
    commands = root.add_subparsers(dest="command")
    start = commands.add_parser("start", help="Primera ejecución: dice qué falta y lo hace")
    start.add_argument("--provider", default="openai", help="Proveedor a configurar")
    key = commands.add_parser("key", help="Guardar una clave de proveedor fuera del entorno")
    key_commands = key.add_subparsers(dest="action", required=True)
    key_set = key_commands.add_parser("set", help="Guardar una clave; se pide sin eco")
    key_set.add_argument("provider")
    key_show = key_commands.add_parser("show", help="Ver si hay clave, nunca su valor")
    key_show.add_argument("provider")
    key_commands.add_parser("list", help="Ver qué proveedores tienen clave")
    key_commands.add_parser("drop", help="Borrar la clave de un proveedor").add_argument("provider")
    commands.required = True
    serve = commands.add_parser("serve", help="Arrancar el coordinador piloto en loopback")
    serve.add_argument("--db", default=".cshcli/coordinator.sqlite3")
    serve.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    auth = commands.add_parser("auth", help="Identidad local de colaboración")
    auth_commands = auth.add_subparsers(dest="action", required=True)
    register = auth_commands.add_parser("register", help="Crear identidad; emite un token personal una sola vez")
    register.add_argument("name")
    project = commands.add_parser("project", help="Proyectos, roles e invitaciones")
    project_commands = project.add_subparsers(dest="action", required=True)
    create = project_commands.add_parser("create")
    create.add_argument("name")
    project_commands.add_parser("list")
    invite = project_commands.add_parser("invite")
    invite.add_argument("project")
    invite.add_argument("--role", choices=["member", "viewer"], default="member")
    invite.add_argument("--ttl", type=int, default=3600)
    join = project_commands.add_parser("join", help="Introducir invitación de forma oculta o por stdin")
    join.add_argument("--invite-stdin", action="store_true")
    memory = commands.add_parser("memory", help="Memoria compartida con versiones")
    memory_commands = memory.add_subparsers(dest="action", required=True)
    read = memory_commands.add_parser("list")
    read.add_argument("project")
    read.add_argument("--limit", type=int, default=10, help="Entradas por página, de 1 a 10")
    read.add_argument("--after", help="next_cursor de la página anterior")
    write = memory_commands.add_parser("put")
    write.add_argument("project")
    write.add_argument("key")
    content = write.add_mutually_exclusive_group(required=True)
    content.add_argument("--content")
    content.add_argument("--file", help="Archivo UTF-8; usa - para stdin")
    write.add_argument("--expected-version", type=int, required=True, help="0 para crear; versión leída para actualizar")
    lease = commands.add_parser("lease", help="Reservas cooperativas de recursos con caducidad")
    lease_commands = lease.add_subparsers(dest="action", required=True)
    acquire = lease_commands.add_parser("acquire")
    acquire.add_argument("project")
    acquire.add_argument("agent")
    acquire.add_argument("resources", nargs="+", help="file:src/path.py, file:src o deploy:staging")
    acquire.add_argument("--ttl", type=int, default=120)
    active = lease_commands.add_parser("list")
    active.add_argument("project")
    for action in ["renew", "release"]:
        operation = lease_commands.add_parser(action)
        operation.add_argument("project")
        operation.add_argument("lease_id")
        operation.add_argument("fence", type=int)
        if action == "renew":
            operation.add_argument("--ttl", type=int, default=120)
    deploy = commands.add_parser("deploy", help="Coordinar un entorno; esta versión solo reserva")
    deployment = deploy.add_subparsers(dest="action", required=True).add_parser("reserve", help="Reserva exclusiva del entorno; no publica artefactos")
    deployment.add_argument("project")
    deployment.add_argument("environment")
    deployment.add_argument("--agent", required=True)
    deployment.add_argument("--ttl", type=int, default=120)
    events = commands.add_parser("events", help="Últimos eventos de auditoría del proyecto")
    events.add_argument("project")
    provider = commands.add_parser("provider", help="Credenciales personales y CLIs oficiales")
    provider_commands = provider.add_subparsers(dest="action", required=True)
    provider_commands.add_parser("status")
    login = provider_commands.add_parser("login", help="Abrir el inicio de sesión del CLI oficial instalado")
    login.add_argument("provider", choices=["codex", "claude", "gemini"])
    chat = commands.add_parser("chat", help="Consulta de texto; claves API en el entorno local")
    chat.add_argument("--provider", choices=["openai", "anthropic", "google", "minimax", "codex", "claude-code", "gemini-cli"], required=True)
    chat.add_argument("--model", help="Modelo explícito obligatorio para API keys")
    chat.add_argument("prompt")

    context = commands.add_parser("context", help="Manifiesto de contexto acotado para una ejecución")
    context.add_argument("project")
    context.add_argument("--task", required=True, help="Identificador de la tarea")
    context.add_argument("--base-sha", required=True, help="SHA base de 40 caracteres sobre el que se trabaja")
    context.add_argument("--budget", type=int, default=65536, help="Presupuesto de bytes; 0 produce un manifiesto vacío")
    context.add_argument("--after-revision", type=int)

    run = commands.add_parser("run", help="Reservas de ejecución con límites y liquidación")
    run_commands = run.add_subparsers(dest="action", required=True)
    run_reserve = run_commands.add_parser("reserve", help="Reservar una ejecución dentro de los límites")
    run_reserve.add_argument("project")
    run_reserve.add_argument("run_id")
    run_reserve.add_argument("--generation", type=int, default=1)
    run_reserve.add_argument("--max-agents", type=int, default=11)
    run_reserve.add_argument("--max-runtime-seconds", type=int)
    run_reserve.add_argument("--allow-unknown-cost", action="store_true")
    run_active = run_commands.add_parser("list", help="Ejecuciones activas que consumen el techo")
    run_active.add_argument("project")
    run_settle = run_commands.add_parser("settle", help="Liquidar el uso medido de una ejecución")
    run_settle.add_argument("project")
    run_settle.add_argument("run_id")
    run_settle.add_argument("attempt_id")
    run_settle.add_argument("--inference-calls", type=int, default=0)
    run_settle.add_argument("--capture-bytes", type=int)
    run_settle.add_argument("--runtime-seconds")
    run_settle.add_argument("--cost", help="Coste real; si se omite se registra como desconocido")

    patch = commands.add_parser("patch", help="Puerta de publicación: decide si un parche puede integrarse")
    patch_commands = patch.add_subparsers(dest="action", required=True)
    patch_accept = patch_commands.add_parser("accept", help="Publicar un parche verificando fences vivos")
    patch_accept.add_argument("project")
    patch_accept.add_argument("run_id")
    patch_accept.add_argument("--base-sha", required=True)
    patch_accept.add_argument("--commit-sha", required=True)
    patch_accept.add_argument("--generation", type=int, default=1)
    patch_accept.add_argument("--lease", action="append", required=True, metavar="RESOURCE=FENCE")
    patch_accept.add_argument("--repo", help="Ruta del repositorio para verificar los commits con Git")
    patch_list = patch_commands.add_parser("list", help="Parches aceptados del proyecto")
    patch_list.add_argument("project")
    patch_list.add_argument("--limit", type=int, default=10)
    return root


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _keyring():
    return Keyring(Path(os.environ.get("CSHCLI_HOME", ".cshcli")))


def _client(args):
    return Client(args.url, os.environ.get("CSHCLI_TOKEN"))


def _key(args):
    ring = _keyring()
    if args.action == "set":
        secret = getpass.getpass(f"Clave de {args.provider} (no se muestra): ",
                                 stream=sys.stderr)
        if not secret.strip():
            print("No se guardó nada: la clave llegó vacía.", file=sys.stderr)
            return 1
        emit(ring.set(args.provider, secret))
        return 0
    if args.action == "drop":
        if not ring.drop(args.provider):
            print(f"No hay clave guardada para {args.provider}.", file=sys.stderr)
            return 1
        print(f"Clave de {args.provider} borrada.")
        return 0
    if args.action == "list":
        emit([ring.describe(name) for name in sorted(PROVIDER_VARIABLES)])
        return 0
    report = ring.describe(args.provider)
    emit(report)
    return 0 if report["configured"] else 1


def _start(client, args):
    """Says what is missing, and stops when there is nothing left to ask."""
    store_ready = identity = project = False
    try:
        listing = client.request("GET", "/v1/projects")
        store_ready = True
        identity = True
        project = bool(listing.get("projects"))
    except DomainError as error:
        if error.status != 503:
            raise
    secret, _ = _keyring().resolve(args.provider)
    step = next_step(store_ready, identity, project, args.provider, secret is not None)
    print(f"\n{step['detail']}\n")
    if step["question"]:
        print(f"  {step['question']}\n")
    print(f"  siguiente: {step['do']}\n")
    return 0


def execute(args):
    if args.command == "key":
        return _key(args)
    if args.command == "start":
        return _start(_client(args), args)
    if args.command == "serve":
        server = make_server(Path(args.db), args.host, args.port)
        print(f"CSHCLI piloto local: http://{args.host}:{server.server_port}", file=sys.stderr)
        print("Las reservas son cooperativas. El runner aislado se implementa en el siguiente hito.", file=sys.stderr)
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0
    if args.command == "provider":
        if args.action == "login":
            return providers.login(args.provider)
        emit(providers.status())
        return 0
    if args.command == "chat":
        print(providers.chat(args.provider, args.model, args.prompt))
        return 0
    token = os.environ.get("CSHCLI_TOKEN")
    if not token and args.command != "auth":
        raise DomainError(401, "authentication_required", "Define CSHCLI_TOKEN con tu token de colaboración.")
    client = Client(args.url, token)
    if args.command == "auth":
        result = client.request("POST", "/v1/users", {"name": args.name})
    elif args.command == "project":
        if args.action == "create":
            result = client.request("POST", "/v1/projects", {"name": args.name})
        elif args.action == "list":
            result = client.request("GET", "/v1/projects")
        elif args.action == "invite":
            result = client.request("POST", f"/v1/projects/{args.project}/invites", {"role": args.role, "ttl": args.ttl})
        else:
            invite = sys.stdin.readline().strip() if args.invite_stdin else getpass.getpass("Invitación: ")
            result = client.request("POST", "/v1/invites/accept", {"token": invite})
    elif args.command == "memory":
        path = f"/v1/projects/{args.project}/memory"
        if args.action == "list":
            query = {"limit": args.limit}
            if args.after is not None:
                query["after"] = args.after
            result = client.request("GET", path + "?" + urlencode(query))
        else:
            text = args.content
            if args.file:
                text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            result = client.request("PUT", path, {"key": args.key, "content": text, "expected_version": args.expected_version})
    elif args.command == "lease":
        path = f"/v1/projects/{args.project}/leases"
        if args.action == "list":
            result = client.request("GET", path)
        elif args.action == "acquire":
            result = client.request("POST", path, {"agent_id": args.agent, "resources": args.resources, "ttl": args.ttl})
        elif args.action == "renew":
            result = client.request("POST", f"{path}/{args.lease_id}/renew", {"fence": args.fence, "ttl": args.ttl})
        else:
            result = client.request("DELETE", f"{path}/{args.lease_id}", {"fence": args.fence})
    elif args.command == "deploy":
        result = client.request("POST", f"/v1/projects/{args.project}/leases", {"agent_id": args.agent, "resources": ["deploy:" + args.environment], "ttl": args.ttl})
    elif args.command == "context":
        payload = {"task_id": args.task, "base_sha": args.base_sha, "context_budget_bytes": args.budget}
        if args.after_revision is not None:
            payload["after_revision"] = args.after_revision
        result = client.request("POST", f"/v1/projects/{args.project}/context", payload)
    elif args.command == "run":
        result = _run(client, args)
    elif args.command == "patch":
        result = _patch(client, args)
    else:
        result = client.request("GET", f"/v1/projects/{args.project}/events")
    emit(result)
    return 0


def _run(client, args):
    base = f"/v1/projects/{args.project}"
    if args.action == "reserve":
        limits = {"max_agents": args.max_agents, "allow_unknown_cost": bool(args.allow_unknown_cost)}
        if args.max_runtime_seconds is not None:
            limits["max_runtime_seconds"] = args.max_runtime_seconds
        return client.request("POST", f"{base}/runs",
                              {"run_id": args.run_id, "authorization_generation": args.generation,
                               "limits": limits})
    if args.action == "list":
        return client.request("GET", f"{base}/runs")
    usage = {"inference_calls": args.inference_calls,
             "capture_bytes": args.capture_bytes, "runtime_seconds": args.runtime_seconds}
    usage["cost"] = args.cost if args.cost is not None else None
    return client.request("POST", f"{base}/runs/settle",
                          {"run_id": args.run_id, "attempt_id": args.attempt_id,
                           "measured_usage": usage})


def _patch(client, args):
    base = f"/v1/projects/{args.project}"
    if args.action == "list":
        return client.request("GET", f"{base}/patches?limit={args.limit}")
    fences = {}
    for entry in args.lease:
        resource, separator, fence = entry.rpartition("=")
        if not separator or not resource or not fence.isdigit():
            raise DomainError(400, "invalid_lease_fence",
                              f"Usa RESOURCE=FENCE en --lease; recibido: {entry}")
        fences[resource] = int(fence)
    payload = {"run_id": args.run_id, "authorization_generation": args.generation,
               "lease_fences": fences, "base_sha": args.base_sha,
               "commit_sha": args.commit_sha}
    if args.repo:
        payload["repo"] = args.repo
    return client.request("POST", f"{base}/patches/accept", payload)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return execute(args)
    except DomainError as error:
        print(json.dumps({"error": {"code": error.code, "message": error.message}}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({"error": {"code": "local_error", "message": "No se pudo leer el archivo local o abrir el servicio; comprueba ruta, permisos y puerto."}}, ensure_ascii=False), file=sys.stderr)
        return 1
