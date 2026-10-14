# Contributing to CSHCLI

Thank you for your interest in improving CSHCLI. This guide explains how to set
up the project, what we expect from a change, and how to submit it.

CSHCLI is currently a local pilot. Read [STATUS](docs/STATUS.md) for what is
implemented and verified, and the [superplan](docs/superpowers/plans/2026-10-14-cshcli.md)
for what is planned. Please do not assume a feature exists because it is
described in the plan.

## Before you begin

| Requirement | Version |
| --- | --- |
| Git | 2.30 or later |
| Python | 3.11 or later |

CSHCLI has **no runtime dependencies** during the pilot. You do not need an AI
account, an API key, or any paid call to build or test the project.

Choose the right channel:

- **Report a bug or request a feature** — open an issue. Describe the problem
  and the outcome you expected, not only the symptom you observed.
- **Discuss a large improvement** — open an issue before writing code. This
  avoids work that conflicts with the architecture or with another contributor.
- **Make a small change** — open a pull request directly.

## Build and test

Run everything from the repository root.

**Windows (PowerShell)**

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python scripts/cshcli.py --help
```

**Linux and macOS**

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python3 scripts/cshcli.py --help
```

The test suite uses real SQLite databases, a real local HTTP server, and
provider fixtures. No test makes a paid call. The AI provider tests exercise
payload construction and error handling against mocks, so they assert the
contract rather than a live account.

**Run the tests before and after your change.** If something already fails,
record the failure and establish whether it is pre-existing or caused by your
change. A pull request that introduces a new failure will not be reviewed.

To run the compilation check locally:

```bash
python -m compileall -q src tests scripts
```

## Coding standards

- **Write the smallest correct change.** Reuse existing code and the standard
  library before adding a dependency or an abstraction.
- **No explanatory comments or docstrings in code.** Document decisions in
  Markdown, where reviewers can read them in context. The codebase is held to
  this rule; new code is held to it too.
- **Preserve the guarantees.** If your change touches permissions, leases,
  memory versions, or concurrency, keep the corresponding validation and the
  tests that prove it. A change that weakens a guarantee is a breaking change
  even if the suite still passes.
- **Never commit secrets.** This includes API keys, coordination tokens,
  databases, and the owner's private memory under `.cshcli/`.

## Commits

Keep commits small, coherent, and buildable. Use a conventional subject:

```text
fix(memory): reject stale expected versions
docs(readme): simplify the first-run example
feat(policy): enforce the concurrency ceiling
```

Explain the reason in the commit body when it carries information the subject
cannot. Do not create empty commits and do not split a single logical change
into artificial steps.

Keep your real authorship. Commits produced by the owner's agents use the
owner's verified Git identity; external contributions keep the identity of
their author.

## Pull requests

A pull request should explain:

1. **The problem** — what is wrong or missing, and why it matters.
2. **The change** — what you did, and what you deliberately did not do.
3. **Verification** — the exact commands you ran and their results.

If the change resolves an issue, reference it with `Closes #N` so GitHub closes
it automatically when the pull request is merged.

Update the documentation when you change an interface. `docs/PROTOCOL.md` is the
contract for the HTTP API; `README.md` and `docs/USAGE.md` are the user-facing
entry points. A behaviour change with no documentation update is incomplete.

The maintainer reviews and integrates proposals. **Opening a pull request is
not the same as merging it.** All contributions are published under the
[MIT License](LICENSE).

## Reporting security issues

Do not open a public issue for a vulnerability. Follow
[SECURITY.md](SECURITY.md) to report privately.

## Continuous integration

CI runs on every push and pull request, on Linux and Windows with Python 3.11,
3.12 and 3.13. It compiles the package, runs the suite, and runs the personal
data guard. See [docs/ci.md](docs/ci.md) for the jobs and their limits.

`Personal data guard` is a **required** check: a pull request that trips the
guard will not merge. It reads the content git is about to record, so run it
yourself before pushing:

```powershell
python scripts/guard_secrets.py --all
```

The guard refuses personal email addresses, private relay addresses, system
user paths, API tokens and private keys, and it requires the noreply git
identity. Install the local hook once with
`python scripts/install_hooks.py`; it never overwrites a hook you already
have.

`main` cannot be pushed to directly, force-pushed or deleted. Everything
arrives through a pull request.