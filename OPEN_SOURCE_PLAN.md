# Full open-source plan

This plan closes the gap between the alpha pilot and a project that meets
the conventions of well-known open-source repositories, without inflating
the maintenance surface beyond what the project can sustain. The
recommendations are calibrated against the eight reference projects
audited on 14 October 2026: microsoft/vscode, cli/cli, astral-sh/uv,
tiangolo/fastapi, python/cpython, rust-lang/rust, kubernetes/kubernetes,
and tokio-rs/tokio.

The plan distinguishes three horizons: ship-now items, near-term items
that require growth, and decisions that should be made explicit now and
deferred in execution.

## 1. Ship now

These changes have no real downside and are aligned with the rules in
this repository.

1. **English throughout the public surface.** Already done in this
   commit. Documents at the root, in `docs/`, and in
   `docs/superpowers/` are in English. Internal owner rules live in
   `AGENTS.md` on the local machine only.
2. **Author and committer identity.** Every commit in the new history is
   authored and committed by the verified owner identity
   `Trankideal <jtpydk5gyh@privaterelay.appleid.com>`. The owner does
   not delegate authorship to AI assistants.
3. **MIT license and required community files.** `LICENSE`,
   `CONTRIBUTING.md`, `SECURITY.md`, and a pull request template are
   already in place.
4. **CHANGELOG.md** following Keep a Changelog, starting with the
   current Unreleased section and the 0.1.0 alpha entry.
5. **`.editorconfig`** with sane defaults for Python, Markdown, YAML,
   and TOML.
6. **`.gitattributes`** to standardise line endings (LF by default, CRLF
   for `.bat`, `.cmd`, and `.ps1`) and mark common binary types.
7. **OSSF Scorecard and CII Best Practices badges** in the README once
   the repository enables branch protection on `main` and signed commits
   are not yet a hard requirement.
8. **Issue and pull request templates** in `.github/ISSUE_TEMPLATE/` with
   three short forms: bug report, feature request, and security report
   (which points to `SECURITY.md`).

## 2. When the project grows

These additions are valuable but not yet worth their maintenance cost.

9. **`.github/dependabot.yml`** for `pip` and `github-actions` with a
   monthly cadence and a 7-day cooldown, once the project depends on
   third-party packages.
10. **`.github/CODEOWNERS`** once the project has at least three active
    reviewers. With one maintainer it becomes a silent bottleneck.
11. **MkDocs site** in `docs/site/` with the Diátaxis split (tutorial,
    how-to, reference, explanation) once the documentation exceeds
    roughly eight pages.
12. **Coverage badge** in the README once coverage stabilises above 70%.
13. **`docs/architecture/` and Architecture Decision Records** for
    decisions that survive more than one release.
14. **`ROADMAP.md`** when a quarterly plan exists; today the superplan
    plays that role.
15. **Ruff and mypy** in CI. Ruff is the de facto Python formatter and
    linter; mypy is the reference type checker. Both can be added
    without breaking the existing 58 tests.

## 3. Decisions to take now, execute later

These do not block the alpha but shape future work.

- **Distribution channel.** PyPI via Trusted Publishing (OIDC) is the
  pattern used by `astral-sh/uv`. It removes long-lived tokens and is
  worth wiring up before the first public release.
- **Commit convention.** The current repository uses
  `type(scope): change` for the owner. A Conventional Commits convention
  with `release-please` would automate the changelog and tags, but it
  conflicts with the owner's preference for the current format. Keep the
  current format; do not add `release-please` unless the owner changes
  their mind.
- **AI assistance policy.** Given the explicit owner rule that all
  commits are attributed to the verified human identity, do not enable
  GitHub's "Allow AI authors" setting. Add a one-line note to
  `CONTRIBUTING.md` stating that commits are human-authored and that AI
  assistance is allowed in code generation but not in authorship.
- **Funding.** Leave `.github/FUNDING.yml` empty until there is a real
  funding destination.
- **Citation.** Skip `CITATION.cff`; CSHCLI is not academic software.

## 4. Anti-patterns to avoid

The audit flagged practices the project must not copy.

- A README that doubles as a marketing brochure. CSHCLI's README must
  stay short and link to the rest of the documentation.
- A long PR template that nobody fills in. The current template has
  three short sections and a verification checklist.
- A `SECURITY.md` that delegates without a contact path. CSHCLI keeps
  its own `SECURITY.md` with a private reporting channel.
- A CHANGELOG that fragments by year and version without an auto-format.
  The project uses a single Keep-a-Changelog file.
- A single-owner CODEOWNERS that creates a silent bottleneck. Add
  CODEOWNERS only with enough reviewers to make it useful.
- Mixing `test/` and `tests/`. The project uses `tests/` exclusively
  (Python convention).

## 5. Verification

- 58 unit tests must pass before and after any of these changes.
- Every commit must be authored and committed by the verified owner
  identity, with no co-authorship from AI assistants.
- Public documents must remain in English; private owner rules remain
  in the local `AGENTS.md` only.
- `python -m compileall -q src tests scripts` must succeed.
- `python scripts/cshcli.py --help` must succeed.
- No new runtime dependencies may enter the pilot without a concrete
  need in the superplan.
