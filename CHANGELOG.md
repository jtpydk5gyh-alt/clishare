# Changelog

All notable changes to CSHCLI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it leaves alpha.

## [Unreleased]

### Security
- The personal data guard now reads the **staged index** instead of the working
  tree. `committed_text` built the git spec as `f"{revision}:{name}"`, which for
  the index revision produces `::name`; git rejects that, and the guard silently
  fell back to scanning the file on disk. It therefore never examined the
  content git was about to record. It now fails closed: a file git cannot
  deliver is reported as unreadable rather than replaced by something else.
- `Personal data guard` is a **required** status check on the `main-integrity`
  ruleset, so a pull request carrying a detected secret can no longer merge.
- `main` can no longer be force-pushed, deleted or updated outside a pull
  request.
- The rewrite helper `scripts/push_rewritten_main.py` now refuses to run against
  a dirty tree instead of destroying uncommitted work with `reset --hard`, and
  its restored ruleset keeps the required check.

### Fixed
- Removed `main-owner-merge`, a second ruleset that duplicated the pull-request
  requirement and rejected every merge with "base branch policy prohibits the
  merge", even with all checks green. Both rulesets had been created thirteen
  seconds after the last successful merge.
- Documented that a squash merge is attributed to the merging account's
  primary email rather than to the branch's commit author. With a private relay
  address set as the account's public primary email, every squash reintroduced
  it. Setting that address to private visibility makes GitHub fall back to the
  noreply form.

### Added
- Milestone 6A: `ContextAssembler` builds a bounded per-run manifest, `Policy`
  reserves and settles runs against an enforced ceiling, and the revision
  metadata `kind`, `scope`, `status`, `source_commit`, `evidence` and
  `expires_at` is stored with an idempotent migration.
- Milestone 8A: `IntegrationGate.accept_patch` is the serialised authority for
  publication, verifying lease fences, lease ownership and expiry, the
  authorisation generation and both SHAs inside one write transaction.
- Milestone 6B: `Workspace` creates isolated git worktrees and refuses
  traversal, absolute paths, Windows reserved names, symbolic links and
  junctions.
- HTTP routes and CLI commands for all of the above: `POST context`,
  `POST/GET runs`, `POST runs/settle`, `POST patches/accept`, `GET patches`,
  plus `cshcli context`, `cshcli run` and `cshcli patch`.
- `minimax` as an AI provider, using its OpenAI-compatible chat completions
  route and the `MINIMAX_API_KEY` credential.
- A health endpoint that probes the database and reports the schema version,
  package version, protocol, uptime and a request counter instead of a
  hardcoded `ok`.
- `scripts/guard_secrets.py` and `scripts/install_hooks.py`: a pre-commit guard
  that refuses personal email addresses, system user paths, tokens and private
  keys, and that also rejects a `git config user.email` other than the noreply
  form.
- `CHANGELOG.md`, an `.editorconfig`, and a `.gitattributes`.
- English translation of every project document.
- Clean history on `main`; the previous Spanish and personal-rule commits are
  retired, and every commit is authored with the noreply address.
- `AGENTS.md` is kept locally on the owner's machine only; it is added to
  `.gitignore` so it never reaches the public remote.

### Changed
- README, PLAN, USAGE, STATUS, REVIEW, PROTOCOL, OPEN_SOURCE, the superplan,
  and the design spec are now written in English.
- `docs/ESTADO.md` was renamed to `docs/STATUS.md`.
- `docs/REVISION.md` was renamed to `docs/REVIEW.md`.
- The `.gitignore` is grouped by the reason for each rule, and the two entries
  that named files which never existed were removed.

### Fixed
- `Policy.finish_run` accepted no caller identity, so any authenticated
  project member could settle another member's run. It now authorises the
  caller and returns `403 reservation_foreign`.
- `max_agents` was validated but not enforced, and could be raised above the
  project ceiling. It now counts live reservations and refuses a larger limit.
- Merging the rebranded tree left the previous package and documents beside
  their replacements, so the repository shipped two importable packages.
- Merging the rewritten tree shipped the new tests without the implementation,
  leaving `main` with a red suite.

### Verification
- **212 tests pass**, 2 skipped where the host refuses symbolic links.
- **CI is active** and green on Windows and Linux with Python 3.11, 3.12 and
  3.13.

### Notes
- This is an alpha pilot. The remote multi-user service, the sandboxed
  runner, the integration queue and real deployments remain in the superplan
  and have not been delivered.
- The `Workspace` boundary is a filesystem boundary, not a sandbox. It does not
  constrain an arbitrary command running inside the workspace.

## [0.1.0] - 2026-10-14

### Added
- Local HTTP coordinator bound to loopback with SQLite WAL persistence.
- Persistent identities, projects, owner, member, and viewer roles, and
  one-use invitations.
- Versioned shared memory with CAS, pagination, and authorship.
- Cooperative file and deployment leases with monotonic fences, TTL
  renewal, and persistent generation across restarts.
- Audit events that exclude secrets, bearer tokens, and full memory
  content.
- CLI with `auth`, `project`, `memory`, `lease`, `deploy`, `events`,
  `provider`, and `chat` subcommands.
- Provider adapters for the OpenAI Responses API, the Anthropic Messages
  API, and the Google `generateContent` API.
- Wrappers for the official Codex and Claude Code CLIs with verified
  safety flags, and a documented refusal for the Gemini CLI chat until a
  no-tool mode is verifiable.
- 58 unit tests covering store races, HTTP contract, provider mocks, and
  the full CLI flow.

### Notes
- Initial public release. The repository was prepared with the OSI MIT
  license, a `CONTRIBUTING.md`, a `SECURITY.md`, and a pull request
  template.
