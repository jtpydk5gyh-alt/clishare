# Verified status of CSHCLI

Date: 16 October 2026. Version **0.9.0**, built locally with `dist/SHA256SUMS` but not published or signed.
Current priority: the [online plan](PLAN-ONLINE.md), whose first three steps
can be done here. The product plan lives in
[the main document](superpowers/plans/2026-10-14-cshcli.md).

## What is verified, and what is not

Every row below names the evidence. Where something is not exercised, the row
says so and the reason is in [OPERATIONS.md](OPERATIONS.md),
[DEPLOYMENTS.md](DEPLOYMENTS.md), [PROVIDERS.md](PROVIDERS.md) or
[RELEASES.md](RELEASES.md).

| Capability | Observed status |
| --- | --- |
| Runnable CLI from source | Help and 0.9.0 version verified |
| Conversational entry point | `cshcli` on its own opens a chat loop when the session is ready, and runs the first-run menu when it is not. Each turn carries the previous ones, capped at 20; the first question also carries the project's shared memory, capped at 8000 characters, and an index of the folder the CLI was opened in, capped at 4000 characters and reporting how many files were left out. `/buscar <texto>` finds where something lives and `/ver <ruta>` reads one file into the conversation, both through the same `Workspace` resolver the mediated runner uses. `/limpiar` clears, `/salir`, `/quit` and Ctrl-D leave. A provider error prints and the loop continues. `cshcli chat "text"` stays a single query. Request bodies per provider are tested; **no provider has been contacted** |
| What the chat can read | The index lists what fits the budget, README, `docs/`, `src/` and `tests/` first, and skips `.git`, `__pycache__`, `node_modules`, `dist` and the usual binary suffixes. `/ver` refuses absolute paths, `..`, Git metadata, symbolic links, Windows junctions and hard links, and refuses a file that is not text. **The chat reads; it executes nothing** |
| Finding things | `/buscar <texto>` returns `ruta:línea: texto`, ignores case, visits exactly the files the index lists, caps the answer and reports the hits it left out. A query with no hits prints that and **does not call the provider**, because the answer is already known locally. Symbolic links and junctions are never opened and binaries are skipped |
| Update check | `cshcli update` compares and reports without changing anything. `--apply` needs the version typed and verifies the checksum first. Tested with a fake transport; **no real download has been performed** |
| First run without instructions | `cshcli start` is a two-option menu that performs the setup: a private session, or joining with an invitation code or creating a shared project. No server is started first: the coordinator is implicit. `cshcli key set` stores a provider key outside the environment. Tested end to end through the real CLI entry point |
| Coordinator lifetime | A command with no reachable coordinator runs one inside its own process on an ephemeral port and closes it on exit. Identity, current project and token live in `.cshcli/session.json`, so later commands need no `--url` and no token. Two embedded coordinators over one database are tested. `cshcli serve` still provides a long-lived one |
| Key storage | `Keyring` in `.cshcli/keys.json`, readable only by the user on POSIX. A key set in the environment wins over one on disk, because whoever exported it knows what they are doing. Nothing ever prints a key |
| Published artefact | Wheel builds, `SHA256SUMS` written, and the **installed** copy imports and answers `--help` on Python 3.12.10, Windows. **Signing is ready, not done**: `release.py` signs by itself once `CSHCLI_SIGNING_KEY` points at the owner's key, and `minisign` 0.12 is installed and verified. **Not published, not checked on other platforms** |
| Local HTTP and SQLite WAL | Two-identity flow tested with a real server |
| owner / member / viewer projects | Read and write paths per permission verified |
| Invitations | Expiration, single use, and races tested |
| Memory | CAS, authorship, persistence, and pagination tested |
| file / deploy leases | Atomic acquisition, prefixes, permissions, expiration, and fences tested |
| AI via API and official CLI | Contracts tested with fixtures; no real calls and no spend |
| Provider capability probe | Reports verified, unknown and unverified facts; never invents pricing |
| Context manifest per run | Built under a byte budget; ACL enforced; superseded entries dropped |
| Run reservations and limits | Ceiling enforced, reconciliation after a crash, unknown usage never zeroed |
| Publication gate | Serialised `accept_patch` verifying fence, owner, expiry, generation and both SHAs |
| Isolated workspace | Per-run git worktree; refuses traversal, symlinks and Windows junctions |
| Mediated runner (6C) | `Runner` validates the lease immediately before every write, stops on heartbeat loss, and exposes no command execution |
| Sandbox | **Not a sandbox.** No CPU, memory, process or network limits. Arbitrary execution stays unimplemented by design |
| Cross-machine service | **Serves over TLS against a real PostgreSQL.** `cshcli serve --remote` binds, wraps the socket and answers `/healthz` with the live database state; plain HTTP on the same port is refused and a client that does not trust the certificate is rejected at the handshake. The certificate is **self-signed**: the TLS path is proven, a public trust chain is not |
| Automatic Git integration | `IntegrationQueue` applies a patch in a dedicated worktree, recomputes the base, runs configured checks on the composed result and advances the branch only through a compare-and-swap. The local HTTP routes can submit, list, read and process entries. Processing fails closed unless `CSHCLI_INTEGRATION_CHECK` is configured. It is **not wired to the runner or a remote worker yet** |
| Usage and budgets (11) | `Usage.record` with `Decimal`, currency, price date and unit; unknown costs stay `null` and are excluded from totals rather than zeroed. `authorize_run` never invents an estimate and refuses when usage is incomplete. Audit export states that retention is unconfigured |
| Chaos drills (11) | **Local drills done.** Stopping the coordinator leaves a running task running, not silently finished; a dead agent's lease expires and a second agent takes the resource; the stale holder cannot renew or release the new lease; state written by one process is read by another; an aborted batch leaves nothing behind; a re-run of an interrupted deploy does not repeat the effect |
| Restore (11) | **Proven on a real PostgreSQL.** `pg_dump` and `pg_restore` into an empty database, row counts compared per table, a restore over a populated database refused, and the fence sequence never observed going backwards. **Not verified:** a restore on a second machine while the first serves traffic |
| Release (11) | Wheel builds, `SHA256SUMS` written, installed copy verified. **Not signed, not published** |
| Deployment publish and rollback | Coordination complete, and the four acceptance checks run against a separate process and a real health socket. **No provider is configured and nothing has been published anywhere** |
| Native direct OAuth | `ProviderAuth` implements PKCE, one-use state, exact loopback redirect and a local store, behind a review registry that is **empty on purpose**. No provider is eligible |
| Personal data guard | Pre-commit hook and a **required** CI check; refuses personal emails, private relay addresses, user paths and a non-noreply identity. Reads the staged index and fails closed |
| Sessions and revocation (7) | `Identity` issues expiring sessions stored as HMAC hashes, and `authorization_generation` refuses work queued before a revocation |
| Remote store (7) | PostgreSQL 16.2 running for real, schema applied and verified, row-locked acquisition, and a refusal to serve while unverified. **Eleven independent processes race for overlapping resources and exactly one wins.** The refusal stays because the criterion it encodes is eleven *machines*, not eleven processes |
| Built web | **Not published**, by decision of the owner. Ignored by git with the reason written next to it |
| Task DAG (8B) | `TaskService` with seven states, cycle refusal on create and modify, and `claim` that acquires leases in the same transaction |
| Integration queue (8B) | Serialised per project, dedicated worktree, recomputed base, configured checks on the composed result, and a compare-and-swap that only advances the branch if it did not move. Local HTTP routes expose submit, list, read and process; processing refuses to run without configured checks, and only a patch the publication gate accepted can be queued |
| Branch governance | Ruleset `main-integrity`: no force-push, no deletion, no direct updates, and `Personal data guard` required to merge |

## Local evidence

Observed environment: Windows with CPython 3.12.14. The interpreter path is
machine specific and is deliberately not recorded here.

With `PYTHONPATH=src`, the command `python -m unittest discover -s tests`
returned **703 passing tests in 422.256 seconds**, with 26 skipped. Every skip
says why: five symbolic link cases on a host that does not grant the
privilege, one POSIX file permission case that does not apply on Windows, and
twenty that need `CSHCLI_REMOTE_DSN` pointing at a real PostgreSQL. Those twenty
**were run** against PostgreSQL 16.2 here, and passed. The Windows junction
cases run.

The two tests that used to fail under load are now independent of the machine:
the capture test gives its child fifteen times the timeout, and the server
test retries only a dropped connection, never an HTTP status. Both were
checked in both directions, including with the code broken on purpose. Concurrent tests use eleven synchronised threads and, for
deployments, eleven processes against one environment; they do not yet
represent eleven distributed machines.

`python -m compileall -q src tests scripts`, `python scripts/cshcli.py --help`,
`python scripts/guard_secrets.py --all` and `python scripts/release.py` were
also executed. The release builds the wheel, writes `SHA256SUMS` and verifies
the installed copy rather than the working tree. The package has no runtime
dependencies; the PostgreSQL driver is an extra.

Real AI accounts, quotas, billing, flags against installed official binaries,
and a deployment target have not been verified. Provider tests use fixtures and
mocks; HTTP, SQLite and git tests use real local components.

**The four acceptance checks now run against a real process.**
`tests/test_deploy_process.py` deploys to a destination whose state is written
by a separate interpreter process and whose health is a real HTTP request to a
localhost server: a staging deploy, a health failure induced by stopping the
server, a rollback, and an idempotent re-send. A fifth check uses a socket that
accepts and never answers, which is a genuine timeout. What remains unverified
is anything needing credentials: a real provider, per-environment secrets and an
environment shared by more than one machine. No provider has been contacted.
See [deployments](DEPLOYMENTS.md).

**CI is active and green.** The workflow runs on every push and pull request
across Windows and Linux with Python 3.11, 3.12 and 3.13. It was published by
pushing the file over git, because the repository token lacks the `workflow`
scope that the contents API requires. The twelve test jobs and the guard pass
on the current `main`, fourteen checks in all, and `Personal data guard` is a
required check on the `main-integrity`
ruleset: a pull request carrying a detected secret cannot merge.

**Attribution of merges is a known trap.** GitHub attributes a squash merge to
the merging account's primary email, not to the branch's commit author. While
the owner's account kept a private relay address as its public primary email,
every squash reintroduced it and the history had to be rewritten again. With
that address set to private visibility, GitHub falls back to the noreply form
and merges stay clean; verified on two consecutive merges without a rewrite.

The sandbox is not verified and **is not implemented**. The plan places
arbitrary execution in a Linux container or VM with verified controls, and
says a native Windows or macOS runner is not to be advertised as equivalent
until its controls are verified. What exists today is the mediated runner: it
validates the lease before every write, refuses any path its workspace will
not resolve, stops on heartbeat loss, and has no method that runs a command.
`Workspace` refuses paths that escape the worktree, including symbolic links
and Windows junctions. What remains is process, memory and network
containment, which needs a container that does not exist yet.

## Rules and decisions

The project started without any existing files. The owner confirmed a set of
working rules that are kept on their own machine and are **not** part of the
public distribution: no explanatory comments in code, minimal changes, tests
run before and after each change, and every commit authored under the owner's
verified Git identity.

Confirmed name: `cshcli`. The initial request was private; the current
decision is to open the project publicly under the OSI MIT license.
Personal memory lives in a local path ignored by Git; it is not part of the
distribution.

No hosting provider or production target has been chosen. Style checks
confirmed zero explanatory comments/docstrings; the guard tests and the rewrite
helper tests are the only intentional exception, since a guard with no tests
cannot be trusted to still guard.

Two decisions about what the chat carries, each with a reason:

- **The index is the folder the CLI was opened in, not the project stored in
  the coordinator.** Someone who writes `cshcli` inside their repository wants
  the agent to talk about that repository. Listing stored names would describe
  the team, not the work in front of them.
- **Reading reuses `Workspace` instead of adding a second path check.** The
  runner already refuses absolute paths, `..`, Git metadata, symbolic links,
  junctions and hard links; a new resolver for the chat would be a new door
  with the same name and one fewer test behind it. The chat reads and executes
  nothing, which keeps the missing sandbox from becoming a missing execution
  surface too.
- **The index and the search share one traversal.** `_walk` replaced the copy
  that lived inside `index_text`, so the two cannot drift apart and quietly
  disagree about what a project contains.
- **A search with no hits costs nothing.** It prints that the project does not
  contain the text and the loop continues. Here the answer is already known
  locally, so paying a provider to be told "nothing" would be spending for
  nothing.

**Working rules added during this work**, all recorded in
[CONTEXT.md](CONTEXT.md) because each one cost something to learn:

- Never use `reset --hard` without looking. It destroyed uncommitted work three
  times, including the rewrite helper's own correction.
- Never weaken a security control so that your own code passes it. The guard
  flagged a test decorator as a possible email address; the test was rewritten
  and the pattern kept.
- Version after a large change. `0.1.0` to `0.2.0` covers a batch that added a
  runner, a DAG, an integration queue, deployments and budgets.
- Update every `.md`, not just the one that changed. Three documents were
  claiming the CI was not active while it had been green for hours, because
  nobody reread them end to end.

## Still to do

| Item | Possible here? |
| --- | --- |
| First run that needs no instructions, with a local key store | Done. `cshcli start` is a two-option menu that performs the setup, and the coordinator is implicit, so no server is started |
| Document the install command with its three caveats | Done |
| `cshcli update` that reports first and installs on consent with a checksum | Done locally, with network doubles. Never exercised against a published release |
| `cshcli serve --remote` over HTTPS with PostgreSQL | **Done here.** It binds, serves `/healthz` over TLS against a live PostgreSQL and refuses plain HTTP. The certificate is self-signed, so this proves the path, not public trust |
| Standing the remote coordinator up and proving real concurrency | **Done on one machine.** Eleven independent processes race and one wins. Eleven *machines* still need a second one |
| Chaos drills and a proven restore | **Done.** `pg_dump` and `pg_restore` into an empty database, counts compared, restore over a populated database refused, fence never rewound. A restore on a second machine is still unproven |
| Signing and publishing the release | **Still no.** The artefact builds and has a checksum, but there is no signing identity. That is the owner's to create |
| Requiring a queue entry to come from an accepted patch | Done. The queue refuses a commit with no accepted-patch record and one accepted with a different base, and rechecks acceptance immediately before the merge |
| The chat starting from the folder it was opened in | Done. The first question carries a capped index of the files, `/buscar <texto>` finds where something lives, and `/ver <ruta>` reads one file into the conversation, all through `Workspace`. Tested through the real CLI entry point |

Each of these is a row above with its evidence, not a promise.

## Two decisions from the owner, 16 October

1. `docs/GITHUB_SUPPORT_TICKET.md` was **deleted**. It had never been tracked,
   held a private address, and blocked commits. Removing it closes the last
   thing the personal data guard kept flagging. Deleted recoverably and outside
   git, so it appears in no commit.
2. **The chat stays read-only.** `/ver` reads and `/buscar` searches; nothing
   writes from the conversation. The publication gate and the integration queue
   exist and are tested, but connecting them to a chat is a different decision:
   the writer would be a model, and a model is not a person reviewing a diff.
   If that changes, the path is `accept_patch` and compare-and-swap.
