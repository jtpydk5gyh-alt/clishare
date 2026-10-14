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
| Isolated editor runner | Proposed, not yet implemented |
| Cross-machine service | Proposed, not yet implemented |
| Automatic Git integration | Proposed, not yet implemented |
| Deployment publish and rollback | Proposed; the pilot only reserves environments |
| Native direct OAuth | Proposed, conditioned on official mechanism and eligibility |

## Local evidence

Observed environment: Windows, Python 3.12.14 from the Codex runtime. The
system `python` alias points to WindowsApps and was not available in this
session. Verification used a standard CPython 3.12 installation; the
interpreter path is machine specific and is deliberately not recorded here.

With `PYTHONPATH=src`, the command `python -m unittest discover -s tests -v`
returned **167 passing tests in 77 seconds**, with 2 skipped: the symbolic link
cases on a host that does not grant the privilege, while the Windows junction
case runs. Concurrent tests use eleven synchronised threads; they do not yet
represent eleven distributed processes.

`python -m compileall -q src tests scripts`, `python scripts/cshcli.py --help`,
and `python scripts/cshcli.py --version` were also executed. The package was
built locally with setuptools, with no runtime dependencies.

Real AI accounts, quotas, billing, flags against installed official binaries,
real Linux/macOS, and a deployment target have not been verified. Provider
tests use fixtures and mocks; HTTP and SQLite tests use real local components.
CI is not activated: GitHub refused to publish the workflow with the current
credential due to the missing `workflow` scope. It is kept as a
[template](templates/ci.yml.example), pending activation; no CI result exists.

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
