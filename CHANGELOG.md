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
- A timeout during the **health check** of a deployment escaped as an unhandled
  exception instead of moving the deployment to `reconciling`. Only `promote`
  was protected. A destination that accepts a connection and never answers can
  now be induced for real, and it found this. The same gap existed while
  reconciling and now leaves the deployment in `reconciling` instead of
  crashing.
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
- Milestone 9: `DeployService` and `DeployWorker`. An idempotency key scoped to
  project and environment, enforced by a database constraint rather than a
  Python check, returns the same deployment for the same payload and `409` for a
  different one. Approval binds the project, environment, commit SHA, artefact
  digest and policy revision. Permission, authorization generation, checks SHA,
  digest and approval are verified twice: before moving to `running` and again
  immediately before the external effect.
- An ambiguous timeout moves to `reconciling` and asks the destination what it
  serves rather than retrying. A destination that cannot answer stays `unknown`
  and stops promotions for that environment. Rollback is conditioned on the
  active deployment, the expected digest and the environment generation, so a
  late rollback cannot undo a newer healthy deployment.
- The four checks in the plan's acceptance line — a staging deploy, an induced
  health failure, a rollback and an idempotent re-send — now run in
  `tests/test_deploy_process.py` against `ProcessDestination`, which writes its
  state from a **separate interpreter process** and answers health over a
  **real HTTP socket**. A fifth check uses a socket that accepts and never
  answers. **No provider is configured and nothing has been published anywhere.**
- Milestone 7 continued: `RemoteStore` for PostgreSQL, with acquisition
  serialised by `SELECT ... FOR UPDATE` on the project row and fences from a
  persistent sequence. It **refuses to serve traffic while unverified**, and
  `verification()` cannot report `verified` without a real server having run.
- `migrations/001_remote.sql`, `deploy/compose.yaml` with the database on a
  private network and no published port, and `docs/OPERATIONS.md` with the
  migration, rollback, backup and restore procedure.
- The PostgreSQL driver is an extra (`cshcli[remote]`), so installing the
  package never drags in a driver the local pilot does not use.
- Milestone 8B: `TaskService` with the `queued`, `running`, `blocked`,
  `review`, `merged`, `failed` and `cancelled` states. A dependency cycle is
  refused when a task is created and again when it is modified. `claim`
  checks dependencies, checks state and acquires the leases inside one write
  transaction, so a task is never running without holding what it needs and
  leases are never held by something that is not running.
- Milestone 8B completed: `IntegrationQueue`. Integration is serialised per
  project, applies each patch in a **dedicated worktree** the user's working
  tree is never part of, recomputes the base so a second patch submitted
  against the same SHA composes on top of the first, runs the checks on the
  composed result, and advances the branch through a **compare-and-swap** that
  fails if anything moved it while the checks ran. A conflict or a failing
  check leaves the item in `review` or `failed`; there is no silent merge. A
  member revoked after acceptance suspends the queue instead of integrating
  under the old permission.
- Milestone 7: `Identity` issues expiring sessions stored only as HMAC-SHA256
  hashes, revokes one session without ending the rest, and raises
  `authorization_generation` so work queued before a revocation cannot act
  afterwards. The PostgreSQL store, HTTPS deployment and restore drill remain
  unverified and are listed as pending.
- Milestone 6C: a mediated `Runner` with `read_file`, `write_file`, `remove`
  and `rename`. Every write validates its lease against the coordinator at the
  moment the bytes move, the runner stops writing when the heartbeat is lost,
  and it exposes no method that runs a command.
- `Store.validate_lease` and `POST /v1/projects/{id}/leases/{lease_id}/validate`,
  which also checks that the requested resource is actually covered by the
  lease. `Client.validate_lease` and `Client.renew_lease` make a real HTTP
  coordinator usable as a runner's lease authority.
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
