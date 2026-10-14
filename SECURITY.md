# Security

CSHCLI 0.1.x is a local pilot and is the only version currently maintained.
The coordinator listens exclusively on loopback. Do not expose it through
tunnels or proxies; the secure remote service is still pending implementation.

## Reporting a vulnerability

Report privately through
[Report a vulnerability](https://github.com/jtpydk5gyh-alt/cshcli/security/advisories/new).
Include the version, the environment, the impact and minimal reproduction
steps. Do not attach keys, tokens, invitations or personal data. Avoid
opening a public issue for an unfixed vulnerability.

## What the repository enforces

| Control | Where | What it does |
| --- | --- | --- |
| Personal data guard | `scripts/guard_secrets.py` | Refuses personal addresses, private relay addresses, system user paths, API tokens and private keys |
| Pre-commit hook | `.git/hooks/pre-commit` | Runs the guard against **the staged index**, before the commit is created |
| CI guard job | `.github/workflows/ci.yml` | Runs the guard over everything tracked, and checks that `main` carries no private relay address |
| Required status check | ruleset `main-integrity` | A pull request cannot merge unless `Personal data guard` passed |
| Branch rules | ruleset `main-integrity` | No force-push to `main`, no deletion, no direct updates: every change arrives through a pull request |

The guard reads the content git is about to record, not the working tree. If
git cannot deliver a file, the guard fails closed rather than scanning
something else and reporting success.

`Personal data guard` is a **required** check. A failing guard blocks the
merge; it does not retroactively remove anything already published. If a
secret ever reaches `main`, removing it needs a history rewrite, and the
account's own email must not reintroduce it on the next merge.

## Known limits

- **No sandbox.** The workspace is a path boundary. It stops a write from
  leaving the worktree; it does not constrain an arbitrary command running
  inside it, and it does not limit memory or processes. See
  [README](README.md) for the full list.
- **Leases are cooperative.** The coordinator records who holds what and
  refuses a second acquisition, but it cannot stop your editor from saving
  over the file. Only the runner will enforce it, in a later milestone.
- **One reviewer.** The repository has a single owner and no second pair of
  eyes. `CODEOWNERS` names that owner, but the ruleset does not enforce code
  owner review, so it is documentation rather than a gate.
- **No dependency scanning.** CI runs `compileall`, the test suite and the
  personal data guard. There is no `ruff`, `mypy`, `bandit` or dependency
  audit yet.

Provider keys are managed locally and never reach the coordinator. See
[Usage](docs/USAGE.md) and [Status](docs/STATUS.md) for the limits.