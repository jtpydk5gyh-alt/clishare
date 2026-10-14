# Continuous integration

## The workflow

CI runs on every push and every pull request, on `ubuntu-latest` and
`windows-latest`, across Python 3.11, 3.12 and 3.13. The workflow lives at
`.github/workflows/ci.yml`.

It was published by pushing the file over git, because the repository token
lacks the `workflow` scope that the REST contents API requires. A copy of the
workflow is kept at `docs/templates/ci.yml.example` so it can be read and
reviewed without workflow permissions.

## Jobs

| Job | What it does |
| --- | --- |
| `Personal data guard` | Scans every tracked file, checks the git identity, and fails if `origin/main` ever carries a private relay address |
| `test (<os>, <python>)` | `compileall`, the full suite, and a CLI smoke test |

`Personal data guard` is a **required** status check on the `main-integrity`
ruleset. A pull request cannot merge unless it passes. `strict` mode is on, so
the branch must also be up to date with `main`.

A failing guard blocks the merge; it does not remove anything already
published. If a secret ever reaches `main`, the fix is a history rewrite with
`python scripts/push_rewritten_main.py`.

## What CI does not cover yet

No `ruff`, no `mypy`, no `bandit`, no dependency vulnerability scan. Those are
listed as pending work in [Status](STATUS.md).

## Dependencies

Dependabot opens pull requests monthly for the `pip` and `github-actions`
ecosystems. Both updates have a 7-day cooldown, so a newly published release
waits before a pull request appears. Configuration lives in
`.github/dependabot.yml`.

## Handling a Dependabot pull request

1. Read the changelog for the bumped package and note any breaking changes.
2. Run the local test suite on the branch and confirm the result.
3. Merge the pull request if the suite passes; otherwise close it with a note
   describing the failure.

Open pull requests are capped per ecosystem, so several bumps can arrive in a
single pull request. If one is too broad to verify, ask Dependabot to split it
into individual updates.