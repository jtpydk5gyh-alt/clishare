# Verified status of CSHCLI

Date: 15 October 2026. Version **0.2.0**, released with `dist/SHA256SUMS`.
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
| Runnable CLI from source | Help and 0.2.0 version verified |
| Update check | `cshcli update` compares and reports without changing anything. `--apply` needs the version typed and verifies the checksum first. Tested with a fake transport; **no real download has been performed** |
| First run without instructions | `cshcli start` says what is missing, in order, and names the exact command for it. `cshcli key set` stores a provider key outside the environment. Tested with a mocked coordinator |
| Key storage | `Keyring` in `.cshcli/keys.json`, readable only by the user on POSIX. A key set in the environment wins over one on disk, because whoever exported it knows what they are doing. Nothing ever prints a key |
| Published artefact | Wheel builds, `SHA256SUMS` written, and the **installed** copy imports and answers `--help` on Python 3.12.10, Windows. **Not signed, not published, not checked on other platforms** |
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
| Cross-machine service | **Not usable.** No server has been run; see [OPERATIONS.md](OPERATIONS.md) |
| Automatic Git integration | `IntegrationQueue` applies a patch in a dedicated worktree, recomputes the base, runs the checks on the composed result and advances the branch only through a compare-and-swap. **Not wired to HTTP or to the runner yet** |
| Usage and budgets (11) | `Usage.record` with `Decimal`, currency, price date and unit; unknown costs stay `null` and are excluded from totals rather than zeroed. `authorize_run` never invents an estimate and refuses when usage is incomplete. Audit export states that retention is unconfigured |
| Chaos drills (11) | **Local drills done.** Stopping the coordinator leaves a running task running, not silently finished; a dead agent's lease expires and a second agent takes the resource; the stale holder cannot renew or release the new lease; state written by one process is read by another; an aborted batch leaves nothing behind; a re-run of an interrupted deploy does not repeat the effect |
| Restore (11) | **Not done.** Needs a real database, so a real restore cannot be proven here |
| Release (11) | Wheel builds, `SHA256SUMS` written, installed copy verified. **Not signed, not published** |
| Deployment publish and rollback | Coordination complete, and the four acceptance checks run against a separate process and a real health socket. **No provider is configured and nothing has been published anywhere** |
| Native direct OAuth | `ProviderAuth` implements PKCE, one-use state, exact loopback redirect and a local store, behind a review registry that is **empty on purpose**. No provider is eligible |
| Personal data guard | Pre-commit hook and a **required** CI check; refuses personal emails, private relay addresses, user paths and a non-noreply identity. Reads the staged index and fails closed |
| Sessions and revocation (7) | `Identity` issues expiring sessions stored as HMAC hashes, and `authorization_generation` refuses work queued before a revocation |
| Remote store (7) | PostgreSQL schema, row-locked acquisition and a refusal to serve while unverified. **No server has been run**; the concurrency test skips with its reason |
| Built web | **Not published**, by decision of the owner. Ignored by git with the reason written next to it |
| Task DAG (8B) | `TaskService` with seven states, cycle refusal on create and modify, and `claim` that acquires leases in the same transaction |
| Integration queue (8B) | Serialised per project, dedicated worktree, recomputed base, checks on the composed result, and a compare-and-swap that only advances the branch if it did not move |
| Branch governance | Ruleset `main-integrity`: no force-push, no deletion, no direct updates, and `Personal data guard` required to merge |

## Local evidence

Observed environment: Windows, Python 3.12.14 from a local toolchain runtime. The
system `python` alias points to WindowsApps and was not available in this
session. Verification used a standard CPython 3.12 installation; the
interpreter path is machine specific and is deliberately not recorded here.

With `PYTHONPATH=src`, the command `python -m unittest discover -s tests -v`
returned **492 passing tests in 183 seconds**, with 5 skipped: two symbolic link
cases on a host that does not grant the privilege, two PostgreSQL cases that
need a real server which does not exist on this machine, and one POSIX file
permission case that does not apply on Windows. The Windows junction case runs.
Concurrent tests use eleven synchronised threads and, for deployments, eleven
processes against one environment; they do not yet represent eleven distributed
machines.

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
scope that the contents API requires. The twelve jobs pass on the current
`main`, and `Personal data guard` is a required check on the `main-integrity`
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
| First run that needs no instructions, with a local key store | Yes |
| Document the install command with its three caveats | Yes |
| `cshcli update` that reports first and installs on consent with a checksum | Yes |
| `cshcli serve --remote` over HTTPS with PostgreSQL | **No.** No server here |
| Standing the remote coordinator up and proving real concurrency | **No.** No PostgreSQL |
| Chaos drills and a proven restore | Partly. Local chaos yes, restore against a real database no |
| Signing the release | **No.** No credentials |

Each of these is a row above with its evidence, not a promise.
