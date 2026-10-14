# CSHCLI

AI CLI with personal credentials and shared project coordination. The idea: you
create a project, invite other people, and everyone works with their own agents
and AI accounts while sharing decisions and reserving files.

## What works today

| Area | What it does |
| --- | --- |
| Projects and roles | `owner`, `member`, `viewer`; one-use invitations with an expiry |
| Shared memory | Versioned writes with compare-and-set, bounded pagination, and revision metadata (`kind`, `scope`, `status`, `evidence`) |
| Resource leases | Atomic acquisition, directory prefixes, TTL renewal and monotonic fences that survive a restart |
| Run limits | A concurrency ceiling that is **enforced**, not merely stored, with reconciliation after a crash |
| Context manifest | One bounded manifest per run, recording exactly which entries and versions it saw |
| Publication gate | A serialised decision that verifies lease fences, ownership, expiry, the authorisation generation and both SHAs before a patch may be published |
| Git verification | The gate can ask the repository whether the commits exist, whether the base is really an ancestor, and which paths the commit actually touches |
| Isolated worktrees | Each run gets its own detached worktree; traversal, absolute paths, reserved Windows names, symbolic links and junctions are refused |
| Revocable authorisation | A generation counter per member and per agent; revoking one invalidates the runs already open |
| AI providers | OpenAI, Anthropic, Google, **MiniMax**, plus the official Codex, Claude Code and Gemini CLIs, with a capability probe that never invents pricing |
| Personal data guard | A pre-commit hook and a CI job that refuse personal addresses, user paths and a git identity other than the noreply form |

## Status

**Local pilot, version 0.1.0.** The coordinator, the CLI, the coordination
store and the publication gate are implemented and covered by tests that run on
Linux and Windows with Python 3.11, 3.12 and 3.13.

What is **not** done, and is stated plainly rather than implied:

- **No sandbox.** The workspace is a path boundary. It stops a write from
  leaving the worktree; it does not constrain an arbitrary command running
  inside it, and it does not limit memory or processes.
- **Leases are cooperative.** The coordinator records who holds what, and
  refuses a second acquisition. It cannot stop your editor from saving over
  the file. Only the runner will enforce that, in a later milestone.
- **No cross-machine service.** The database is a local SQLite file. Two
  people cannot collaborate through this yet.
- **No real deployments.** `deploy reserve` reserves an environment name. It
  publishes nothing.

The [full plan](docs/superpowers/plans/2026-10-14-cshcli.md), the
[design](docs/superpowers/specs/2026-10-14-cshcli-design.md), the
[status](docs/STATUS.md) and the [HTTP protocol](docs/PROTOCOL.md) describe
requirements, phases, permissions, invariants, risks, and acceptance criteria.

## Run from source

Requirement: Python 3.11 or later. The pilot needs no runtime dependencies. From
the repository root:

```powershell
python scripts/cshcli.py --help
python scripts/cshcli.py serve
```

The coordinator listens on `http://127.0.0.1:8765` and stores its database in
`.cshcli/coordinator.sqlite3`. That folder is ignored by Git. The server in
this cut only accepts loopback; the remote service phase covers HTTPS, verified
identity, request limits, and member administration.

To install the command in a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\cshcli --help
```

On Linux/macOS: `.venv/bin/python -m pip install -e .` and `.venv/bin/cshcli`.
Packaging uses setuptools; the first install command may download it.

## Create a project and invite someone

Keep the server running in the first terminal. In a second PowerShell:

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

**Current limit:** a lease is an agreement verified by the coordinator. It does
not yet intercept writes from external tools, nor does it link the chat with
an editor agent. The runner and patch validation in the next milestone will
enforce those leases on code changes.

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
# Pick a model available on your account and set the API key only in your shell.
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

## Coordinate deployments

```powershell
python scripts/cshcli.py deploy reserve $projectId staging --agent ana-release --ttl 120
```

Only the owner can reserve `deploy:staging`; a second attempt on the same
environment fails while the lease is still active. Renew and release it with
`lease`. **This command reserves the environment; it does not deploy.** The
plan covers a persistent queue, exact SHA and digest, idempotency, checks,
publishing, health checks, reconciliation after failures, and rollback.

## Verification

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests scripts
python scripts/cshcli.py --help
```

The tests use real SQLite, local HTTP, and provider fixtures. The synchronised
races pit eleven agents from two people against the same resource, memory
version, and invitation. They check permissions, expiration, persistent
fencing, paths, atomic batches, and the absence of secrets in audit logs.
Provider tests do not make paid calls or verify real logins.

The [GitHub Actions template](docs/templates/ci.yml.example) will run the
suite on Windows and Linux with Python 3.11, 3.12, and 3.13 once it is
activated as `.github/workflows/ci.yml`. The credential used for the first
push cannot publish workflows; CI remains pending activation with the
required permission.

## Next deliveries

1. Remote service with HTTPS, verified accounts, token rotation, and member revocation.
2. Per-task runner with worktrees, heartbeat, mediated tools, and path/symlink control.
3. Tasks and quotas per person/provider, evidence-backed memory, and integration queue over SHA.
4. Per-environment deployment pipeline with verifiable artefacts and rollback.
5. Eligible native OAuth, streaming, cost metrics, packaging, and distribution.

The plan develops each delivery with contracts, tests, and closure conditions.
