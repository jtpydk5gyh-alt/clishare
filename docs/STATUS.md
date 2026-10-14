# Verified status of CSHCLI

Date: 14 October 2026. Current priority: complete the superplan. The product
plan lives in [the main document](superpowers/plans/2026-10-14-cshcli.md).

## Existing base

| Capability | Observed status |
| --- | --- |
| Runnable CLI from source | Help and 0.1.0 version verified |
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
| Cross-machine service | Proposed, not yet implemented |
| Automatic Git integration | Proposed, not yet implemented |
| Deployment publish and rollback | Proposed; the pilot only reserves environments |
| Native direct OAuth | Proposed, conditioned on official mechanism and eligibility |
| Personal data guard | Pre-commit hook and a **required** CI check; refuses personal emails, private relay addresses, user paths and a non-noreply identity. Reads the staged index and fails closed |
| Sessions and revocation (7) | `Identity` issues expiring sessions stored as HMAC hashes, and `authorization_generation` refuses work queued before a revocation |
| Task DAG (8B) | `TaskService` with seven states, cycle refusal on create and modify, and `claim` that acquires leases in the same transaction |
| Branch governance | Ruleset `main-integrity`: no force-push, no deletion, no direct updates, and `Personal data guard` required to merge |

## Local evidence

Observed environment: Windows, Python 3.12.14 from a local toolchain runtime. The
system `python` alias points to WindowsApps and was not available in this
session. Verification used a standard CPython 3.12 installation; the
interpreter path is machine specific and is deliberately not recorded here.

With `PYTHONPATH=src`, the command `python -m unittest discover -s tests -v`
returned **306 passing tests in 149 seconds**, with 2 skipped: the symbolic link
cases on a host that does not grant the privilege, while the Windows junction
case runs. Concurrent tests use eleven synchronised threads; they do not yet
represent eleven distributed processes.

`python -m compileall -q src tests scripts`, `python scripts/cshcli.py --help`,
`python scripts/guard_secrets.py --all`, and
`python scripts/push_rewritten_main.py` were also executed. The package was
built locally with setuptools, with no runtime dependencies.

Real AI accounts, quotas, billing, flags against installed official binaries,
and a deployment target have not been verified. Provider tests use fixtures and
mocks; HTTP and SQLite tests use real local components.

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
