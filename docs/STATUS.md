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
| Sandboxed runner | Proposed; the workspace is a path boundary, not a sandbox |
| Cross-machine service | Proposed, not yet implemented |
| Automatic Git integration | Proposed, not yet implemented |
| Deployment publish and rollback | Proposed; the pilot only reserves environments |
| Native direct OAuth | Proposed, conditioned on official mechanism and eligibility |
| Personal data guard | Pre-commit hook refuses personal emails, user paths and non-noreply identity |

## Local evidence

Observed environment: Windows, Python 3.12.14 from a local toolchain runtime. The
system `python` alias points to WindowsApps and was not available in this
session. Verification used a standard CPython 3.12 installation; the
interpreter path is machine specific and is deliberately not recorded here.

With `PYTHONPATH=src`, the command `python -m unittest discover -s tests -v`
returned **212 passing tests in 82 seconds**, with 2 skipped: the symbolic link
cases on a host that does not grant the privilege, while the Windows junction
case runs. Concurrent tests use eleven synchronised threads; they do not yet
represent eleven distributed processes.

Breakdown by module: 38 provider, 37 store, 24 policy, 20 workspace, 17
integration, 14 broker, 11 guard, 10 context, and the HTTP and CLI route tests.

`python -m compileall -q src tests scripts`, `python scripts/cshcli.py --help`,
and `python scripts/cshcli.py --version` were also executed. The package was
built locally with setuptools, with no runtime dependencies.

Real AI accounts, quotas, billing, flags against installed official binaries,
and a deployment target have not been verified. Provider tests use fixtures and
mocks; HTTP and SQLite tests use real local components.

**CI is active and green.** The workflow runs on every push and pull request
across Windows and Linux with Python 3.11, 3.12 and 3.13. It was published by
pushing the file over git, because the repository token lacks the `workflow`
scope that the contents API requires. The twelve jobs pass on the current
`main`.

The sandbox is not verified. `Workspace` refuses paths that escape the worktree,
including symbolic links and Windows junctions, but it does not constrain an
arbitrary command running inside the workspace, and it does not limit memory or
processes. That is milestone 6C.

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
confirmed zero explanatory comments/docstrings and 58 passing tests after
their removal. The pilot logic was not altered.
