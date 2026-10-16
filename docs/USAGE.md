# CSHCLI

AI CLI with personal credentials and shared project coordination. The idea: you
create a project, invite other people, and everyone works with their own agents
and AI accounts while sharing decisions and reserving files.

**Status: local 0.5.0 pilot.** The CLI, local HTTP coordinator, SQLite, projects,
invitations, versioned memory, leases, text-based AI adapters, mediated runner,
automatic worktrees, task DAG, local integration queue, deployment coordination,
usage and budgets are in place. The remote multi-user service and a real cloud
destination are blocked on external infrastructure.

The [full plan](superpowers/plans/2026-10-14-cshcli.md), the
[design](superpowers/specs/2026-10-14-cshcli-design.md), and the
[HTTP protocol](PROTOCOL.md) describe requirements, phases, permissions,
invariants, risks, and acceptance criteria.

## Run from source

Requirement: Python 3.11 or later. The pilot needs no runtime dependencies.

```powershell
python scripts/cshcli.py start
```

`start` is the only command a new user needs. It asks two questions and does the
rest:

```text
  CSHCLI 0.5.0 — coordinas agentes con tus propias cuentas

  1) Sesión           Trabaja por tu cuenta
  2) Unirme o crear   Un proyecto compartido con otra persona

  Elige 1 o 2:
```

Choosing **1** asks your name, names a project and stores a provider key.
Choosing **2** asks whether you have an invitation code; with one you join,
without one you create a project and receive a code to hand to someone else.

Nothing needs to be running first. When no coordinator is reachable, each
command starts one inside its own process on an ephemeral port and closes it on
exit. Your name, current project, provider and token are kept in
`.cshcli/session.json`, so later commands work with no `--url`, no
`CSHCLI_TOKEN` and no server.

Once the session is ready, `cshcli` on its own opens a chat:

```text
  ana · demo · openai    /salir para salir

> _
```

Type a line, get an answer, type the next one. The loop carries the
conversation: each turn sends the previous turns, capped at the last 20 so it
cannot grow without bound. `/limpiar` clears it, `/salir`, `/quit` or Ctrl-D
leaves. A provider error is printed and the loop continues rather than exiting.

**No provider has been contacted.** The wire format per provider is covered by
tests against the request body, not against a live API.

For API providers the model identifier is explicit and required, because the
tool does not guess one. `cshcli --model gpt-4o-mini` sets it for the session;
`cshcli chat --provider openai --model gpt-4o-mini "one question"` stays a
single query without entering the loop.

Other commands need nothing either:

```powershell
python scripts/cshcli.py project list
```

The database lives in `.cshcli/coordinator.sqlite3` and holds every decision, so
the coordinator that made them does not need to keep running. That folder is
ignored by Git. The pilot coordinator only accepts loopback; the remote service
phase covers HTTPS, verified identity, request limits, and member
administration.

`cshcli serve` still starts a long-lived coordinator others can reach. If one is
already listening on `127.0.0.1:8765`, the CLI uses it. `--url` or `CSHCLI_URL`
forces a specific coordinator, and that is the only supported path to a shared
one.

To install the command in a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\cshcli start
```

On Linux/macOS: `.venv/bin/python -m pip install -e .` and `.venv/bin/cshcli`.
Packaging uses setuptools; the first install command may download it.

## Create a project and invite someone

Run `cshcli start`, choose **2**, decline the invitation question and name a
project. It prints an invitation code. The other person runs `cshcli start`,
chooses **2**, answers that they have a code and pastes it.

The commands below still exist for scripts and need `CSHCLI_TOKEN` when there is
no local session:

```powershell
$identity = python scripts/cshcli.py auth register ana | ConvertFrom-Json
$env:CSHCLI_TOKEN = $identity.token
$project = python scripts/cshcli.py project create my-project | ConvertFrom-Json
$projectId = $project.id
python scripts/cshcli.py project list
python scripts/cshcli.py project invite $projectId --role member --ttl 3600
```

The personal registration token is delivered once and only its hash is stored
in the database. Keep it in a local secure store; this cut has no recovery or
token rotation. The invitation is also returned once, expires, and can only be
accepted once. Share it with its recipient over a private channel. CSHCLI
does not send messages or invitations by email automatically.

In another terminal that reaches the same local coordinator:

```powershell
$identity = python scripts/cshcli.py auth register luis | ConvertFrom-Json
$env:CSHCLI_TOKEN = $identity.token
python scripts/cshcli.py project join
python scripts/cshcli.py project list
```

`project join` requests the invitation without showing it. It also accepts
`--invite-stdin` for automation. This example demonstrates two identities on a
single machine; cross-machine collaboration needs the remote service phase.

| Role | Read project, memory, leases, and events | Edit memory and reserve files | Invite and reserve deployments |
| --- | --- | --- | --- |
| owner | Yes | Yes | Yes |
| member | Yes | Yes | No |
| viewer | Yes | No | No |

## Memory and leases

```powershell
python scripts/cshcli.py memory put $projectId architecture --content "One worktree per task" --expected-version 0
python scripts/cshcli.py memory list $projectId
python scripts/cshcli.py memory put $projectId architecture --content "One worktree and one branch per task" --expected-version 1
python scripts/cshcli.py lease acquire $projectId ana-1 file:src/auth.py file:tests/test_auth.py --ttl 120
python scripts/cshcli.py lease list $projectId
```

Each memory entry has an author, a timestamp, and a version. `0` creates an
entry; an update must reference the latest version read. `memory list` returns
`items` and `next_cursor`; if there are more entries, use `--after` with that
cursor. `--limit` accepts between 1 and 10 entries per page. A conflict returns
error 409 and forces a re-read, preventing you from overwriting someone else's
change. You can also use `memory put ... --file path.md --expected-version N`
or `--file -`.

A lease on `file:src` conflicts with `file:src/auth.py`. Disjoint resources can
be worked on in parallel. A batch is acquired in full or rejected in full.
Paths are relative, use `/`, and disallow `..`, absolute paths, and ambiguous
Windows names; the coordinator compares case conservatively.

The response includes `id`, `fence`, and `expires_at` for each resource. Renew
before the lease expires and reuse the values from that lease:

```powershell
python scripts/cshcli.py lease renew $projectId LEASE_ID FENCE --ttl 120
python scripts/cshcli.py lease release $projectId LEASE_ID FENCE
python scripts/cshcli.py events $projectId
```

Default TTL: 120 seconds; range: 1–3600. Renewal is manual in this cut. Fences
are monotonic and persistent: a former holder cannot renew or release an
expired or reassigned lease with a stale value.

**Current limit:** the mediated runner validates leases before its own file
writes and stops after heartbeat loss, but it does not intercept writes from
external tools. It exposes no arbitrary command execution and is not a process
sandbox.

## AI accounts and API keys

The CSHCLI identity and the AI accounts are independent. The coordinator does
not receive provider keys; calls are made from the local CLI.

```powershell
python scripts/cshcli.py provider status
python scripts/cshcli.py provider login codex
python scripts/cshcli.py provider login claude
python scripts/cshcli.py provider login gemini
```

The login commands execute the installed official CLI and let it manage its own
authentication. They do not copy OAuth tokens or credential files. You need a
compatible version and the binary in your PATH; on Windows this adapter
requires a native binary, because `.cmd/.bat` wrappers do not preserve all
argument guarantees. Gemini installed via npm typically uses a wrapper; in that
case, sign in directly with its official command and use its API here.

| `chat --provider` | Local credential | Status |
| --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | Responses API, explicit model |
| `anthropic` | `ANTHROPIC_API_KEY` | Messages API, explicit model |
| `google` | `GEMINI_API_KEY` | generateContent API, explicit model |
| `codex` | Official CLI auth | Text with read-only sandbox and verified flags |
| `claude-code` | Official CLI auth | Text with tools disabled and verified flags |
| `gemini-cli` | Official CLI auth | Chat blocked until verifiable isolation is available |

```powershell
$env:CSHCLI_MODEL = "model-identifier"
python scripts/cshcli.py chat --provider openai --model $env:CSHCLI_MODEL "Explain this design"
python scripts/cshcli.py chat --provider codex "Propose a migration plan"
python scripts/cshcli.py chat --provider claude-code "Review this architecture decision"
```

The current chat accepts text only; it does not attach or traverse the
repository. The official account CLIs run the chat from an empty temporary
folder. If the required flags are missing, the adapter returns an error. The
official CLI's managed policies still apply; the wrapper is not a universal
sandbox.

CSHCLI API variables and `CSHCLI_*` are stripped from the subprocess
environment. Authentication and billing for those CLIs still depend on their
official configuration. A subscription and an API key may have different quotas
and billing. CSHCLI does not silently switch provider or billing mode after
an error.

OpenAI also documents an official
[Sign in with ChatGPT](https://developers.openai.com/siwc/quickstart) path.
Direct integration will be evaluated with a dedicated client and its
eligibility: the private repository does not grant automatic access. Claude
Code and Gemini CLI keep their own login flows; the roadmap records the
restrictions of each provider and the official sources.

`.env.example` only documents variables: the CLI does not load `.env`
automatically. Do not put secrets in prompts, memory, events, or versioned
files. Provider errors omit remote bodies and stderr to avoid leaking
credentials.

## Integrate queued Git commits

Before starting the coordinator, point it at the repository and configure the
check command as a JSON array. The command runs without a shell in a dedicated
integration worktree, with a 240-second timeout:

```powershell
$env:CSHCLI_REPOSITORY = (Get-Location).Path
$env:CSHCLI_INTEGRATION_CHECK = '["python","-m","unittest","discover","-s","tests"]'
```

Processing a queue entry is an explicit `cshcli` call, so no long-lived
coordinator is required for this either.

The HTTP API can submit, list, read and process queue entries:

- `POST /v1/projects/{project_id}/queue`
- `GET /v1/projects/{project_id}/queue`
- `GET /v1/projects/{project_id}/queue/{entry_id}`
- `POST /v1/projects/{project_id}/queue/next`

Submitting and processing require a `writer` or `owner`; reading requires any
project membership. Only the `owner` can name a different `repository` or
`branch` in a request, so a member cannot point the integrator at another path
on the machine. Processing a non-empty queue without `CSHCLI_INTEGRATION_CHECK`
returns `409 checks_not_configured` and leaves the branch untouched. A conflict or branch movement goes to review. A failing check
leaves the item failed. None of those paths is a silent merge.

This is still local Git integration, not a multi-host worker. Only the owner may
name a repository path per request, because the coordinator is loopback-only;
a non-owner cannot. Do not publish this pilot through a tunnel or reverse proxy.
A queue entry requires a prior accepted-patch record, so the publication gate is
what decides what may be merged.

## Coordinate deployments

```powershell
python scripts/cshcli.py deploy reserve $projectId staging --agent ana-release --ttl 120
```

Only the owner can reserve `deploy:staging`; a second attempt on the same
environment fails while the lease is still active. Renew and release it with
`lease`. **This command only reserves the environment.** The deployment core
has a persistent queue, exact SHA and digest, idempotency, recorded checks,
health checks, reconciliation and rollback, tested against a separate process
and a real local health socket. No cloud destination is configured and nothing
has been published.

## Verification

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests scripts
python scripts/cshcli.py --help
```

The current Windows run passes 558 tests with 5 explicit skips for unavailable
POSIX symbolic-link/file-permission guarantees and real PostgreSQL. The tests
use real SQLite, local HTTP, Git, and provider fixtures. The synchronised
races pit eleven agents from two people against the same resource, memory
version, and invitation. They check permissions, expiration, persistent
fencing, paths, atomic batches, and the absence of secrets in audit logs.
Provider tests do not make paid calls or verify real logins.

The active GitHub Actions workflow runs the suite on Windows and Linux with
Python 3.11, 3.12, and 3.13. The required `Personal data guard` check also runs
against the commit being merged.

## Next deliveries

1. Remote service with real HTTPS and PostgreSQL, after concurrency and restore drills pass.
2. A signed and published release whose wheel and `SHA256SUMS` URLs are exercised end to end.
3. Windows protection for the local key store beyond ordinary file placement.
4. Native provider OAuth only after an explicit provider-by-provider eligibility review.
5. The conversation carried between turns, verified against at least one live provider.

The plan develops each delivery with contracts, tests, and closure conditions.
