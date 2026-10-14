# Continuous integration

## Workflow template

The CI workflow template lives at `docs/templates/ci.yml.example`. It is a
plain file in the repository so it can be read, reviewed, and copied without
workflow permissions.

It is not an active workflow. Moving it to `.github/workflows/ci.yml` happens
when the repository has permission to publish workflows, and that move is the
only change that activates it. Until then, the example is documentation, not a
running check.

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