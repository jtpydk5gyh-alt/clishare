# Changelog

All notable changes to CSHCLI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it leaves alpha.

## [Unreleased]

### Removed
- `docs/GITHUB_SUPPORT_TICKET.md`. It was never tracked, held a private
  address, and blocked commits. Since 0.7.0 the chat index listed it, so
  `/ver` could have read it and sent it to a provider.

## [0.8.0] - 2026-10-16

The chat can search the project before it opens anything.

### Added
- `/buscar <texto>` finds where something lives and puts the hits into the
  conversation as `ruta:línea: texto`. The search ignores case, visits exactly
  the files the index lists, caps the answer at 4000 characters and 20 hits per
  line shown, and reports how many hits were left out.
- `cshcli.knowledge.search_text`. It reads through `Workspace`, so a symbolic
  link, a Windows junction or a hard link pointing outside the folder is never
  opened, a binary is skipped rather than searched, and `.git`,
  `__pycache__`, `node_modules` and `dist` are not searched at all.
- `run_loop` takes an optional `search`. With no searcher behind it, `/buscar`
  is refused rather than sent to a provider as if it were a question.

### Changed
- The index and the search share one traversal. `_walk` replaces the copy that
  lived inside `index_text`, so the two can no longer drift apart and quietly
  disagree about what a project contains.
- The chat banner now reads `/buscar <texto>, /ver <archivo>, /limpiar, /salir`.

### Fixed
- A search with no hits no longer calls the provider. It prints that the project
  does not contain the text and the loop continues. Paying for an answer whose
  content is already known is spending for nothing.

**Not verified:** no provider has been contacted, so what a model does with the
hits is not known. That a query with no hits costs nothing is checked here,
because that is decided locally.

## [0.7.0] - 2026-10-16

The chat knows which project it is in.

### Added
- `cshcli.knowledge`: an index of the folder the CLI was opened in, and a reader
  for one file. The first question of the loop carries the index, so a
  conversation starts knowing what exists instead of being told.
- `/ver <ruta>` reads a file into the conversation as a fenced block, and the
  answer comes back like any other turn. A missing path, a binary file or a
  refused path prints the reason and the loop continues.
- The index lists what fits a 4000 character budget, README, `docs/`, `src/`,
  `tests/` and `test/` first, and says how many files were left out instead of
  pretending the list is complete. `.git`, `__pycache__`, `node_modules`, `dist`
  and the usual binary suffixes are skipped.

Reading goes through `Workspace`, the same resolver the mediated runner uses,
so absolute paths, `..`, Git metadata, symbolic links, Windows junctions and
hard links are refused exactly as they are on a write. No second path check was
invented for the chat, and **nothing is executed**: the chat reads, it does not
run commands.

### Changed
- The chat banner advertises `/ver`, and its text no longer contains a leftover
  `forget` from an earlier draft.
- `run_loop` takes an optional `note`. With no reader behind it, `/ver` is
  refused rather than sent to a provider as if it were a question.

**Not verified:** no provider has been contacted, so what a model does with the
index and the file is not known. The index and the block are built and capped by
tests; the reasoning that follows is the provider's, not something measured
here.

## [0.6.0] - 2026-10-16

The chat stops starting from nothing.

### Added
- The chat's first question carries the project's shared memory as a delimited
  block, capped at 8000 characters, so a conversation starts from what the team
  already decided instead of from nothing. An entry with an empty key or empty
  content is skipped rather than rendered as a malformed line.
- `project_context` builds that block, and `run_loop` takes it as `context`.

The block travels as part of the first user question rather than as a separate
system message: each provider spells that differently and none of it has been
checked against a live API.

- `scripts/bump_version.py` and `tests/test_bump_version.py`. The script rewrites
  the version across the package and the documents and refuses when a sentence
  no longer matches exactly once; the test asserts that property against the
  real repository, so reworded documentation fails a test instead of failing
  silently at release time. The procedure is in `docs/RELEASES.md`.
- The chat loop carries the conversation: each turn sends the previous turns,
  capped at the last 20 so it cannot grow without bound. `/limpiar` clears it.
- `providers.chat` and `_api_chat` accept an optional `history`, and the request
  body is built per provider: `messages` for Anthropic and MiniMax, `contents`
  with `role: model` for Google, and typed `input` blocks for OpenAI. An
  unusable history entry is dropped rather than sent.
- A turn that failed is **not** remembered, so a provider error does not leave
  a half-turn in the next request.

**Not verified:** no provider has been contacted. The request body per provider
is covered by tests that capture what would be sent, not by a live API call.

## [0.5.0] - 2026-10-16

`cshcli` on its own now opens a chat.

### Added
- A conversational loop. With a ready session, `cshcli` prints a banner and
  reads lines until `/salir`, `/quit` or Ctrl-D. A provider error is printed
  and the loop continues rather than ending the session.
- `run_loop` takes the ask function, so the loop is tested without contacting a
  provider.
- `--provider` and `--model` at the root, so they work for the bare command and
  for `cshcli chat` alike.
- The wizard records the provider, and reuses a key that is already stored
  instead of asking which provider to use.

### Changed
- `cshcli chat` no longer requires `--provider`: it falls back to the provider
  in the session. `prompt` is now optional, and without it the command enters
  the loop instead of printing one answer.
- A bare `cshcli` runs the first-run menu only when the session is not ready.

## [0.4.0] - 2026-10-16

The first run was eight commands across two terminals, and `start` only printed
what to run next. It is now one command that does the work.

### Security
- The integration queue now **requires a prior accepted-patch record**. A commit
  the publication gate never accepted is refused with `409 patch_not_accepted`,
  and one accepted with a different base with `409 patch_base_mismatch`.
  Acceptance is rechecked immediately before the merge, so a record withdrawn
  while the entry waited is refused instead of merged. Previously the HTTP queue
  could merge any commit in the repository.
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
- The integration queue's compare-and-swap could not fail. `update-ref` ran with
  the default `check=True`, so a branch that moved between the last read and the
  update raised `CalledProcessError` instead of returning `None`. The "branch
  moved before the update" outcome was unreachable and the race escaped as an
  internal error rather than a review. It now returns `None` and settles to
  `review`, leaving the other writer's commit intact.
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
- `cshcli start` is now a menu that performs the setup instead of printing the
  next command. Option 1 prepares a private session; option 2 joins with an
  invitation code or creates a shared project and prints a code to share.
- The coordinator is now implicit. When none is reachable, every command runs one
  inside its own process on an ephemeral port and closes it on exit, so a single
  user never starts or keeps a server. `cshcli serve` still provides a
  long-lived coordinator, and `--url`/`CSHCLI_URL` still selects a shared one.
- `.cshcli/session.json` stores the name, current project and token, so later
  commands need neither `--url` nor `CSHCLI_TOKEN`.
- Local HTTP routes for the integration queue: submit, list, read and process.
  Queue writes require a writer or owner, reads require project membership, entry
  lookup is scoped to the project, and only the owner may override `repository`
  or `branch` in a request.
- `CSHCLI_INTEGRATION_CHECK`, a JSON command array run without a shell in the
  dedicated integration worktree with a 240-second timeout. Processing a
  non-empty queue fails closed when no check command is configured.
- Chaos drills that break real things locally: stopping the coordinator leaves
  a running task running rather than silently finishing it, a dead agent's lease
  expires and a second agent takes the resource, the stale holder cannot renew
  or release the new lease, a separate process reads what another wrote, an
  aborted batch leaves nothing behind, and a re-run of an interrupted deployment
  does not repeat the effect. Restore against a real database and the drills
  against a real provider remain unverified and are listed as such.
- `cshcli update`: compares the installed version with the published one and
  reports. It changes nothing on disk. `update --apply` requires the version to
  be typed and **verifies the checksum before installing**; an artefact that
  fails verification is deleted rather than left where it could be mistaken for
  a package. When no release is published the answer is `unknown`, never "up to
  date", because claiming to have checked something that was not checked is the
  same mistake this repository avoids everywhere else.
- `cshcli start`: the first run says what is missing, in order, and names the
  exact command for it. Reaching something useful took four commands and an
  environment variable; that was a shape problem, not a documentation one.
- `cshcli key set|show|list|drop` and a `Keyring` in `.cshcli/keys.json`,
  readable only by the user on POSIX. A key in the environment still wins over
  one on disk, because whoever exported it knows what they are doing. Nothing
  ever prints a key, and a test checks that asking about one provider does not
  reveal another's.
- Recorded where the project actually stands: version 0.3.0, 52 commits on
  `origin/main`, 581 passing tests, and a table that says for each remaining
  item whether it can be done on this machine. The document states what cannot
  be checked instead of implying it.
- `docs/STATUS.md` gained a "What is verified, and what is not" heading, a
  "Still to do" table, and the working rules that cost something to learn:
  never `reset --hard` without looking, never weaken a security control so
  your own code passes it, version after a large change, and update every
  `.md` rather than the one that changed.
- The install command the owner asked about is now documented in the README
  **with its three caveats**: it installs `main` and not a version, it checks
  nothing, and `cshcli` may not land on your PATH while `py -m cshcli` always
  works.
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
- `docs/PLAN-ONLINE.md`: the plan for running online, for a first run that
  needs no instructions, for an install command with its three caveats, and
  for an update that reports first and only installs on explicit consent with
  a checksum check. **Nothing in it is implemented yet**, and the document says
  so in its first paragraph.
- Milestone 11: `Usage` and `BudgetPolicy`. Amounts use `Decimal`, and a cost
  without a currency or without the date its price was read is refused rather
  than stored. **Unknown values stay `null` and are excluded from totals, never
  counted as zero.** `authorize_run` never invents an estimate: with a budget
  and no estimate it refuses with `estimate_required`, and with an unpriced
  recorded call it refuses with `usage_incomplete`.
- `max_agents` is enforced against the active run reservations, so the eleventh
  agent against a ceiling of ten is refused.
- A usage record carries request id, project, task, agent, lease and fence, and
  a test asserts the emitted event contains no prompt, token or provider
  variable name. The audit export states that retention is not configured.
- **Fixed:** filtering usage by currency in SQL made an unpriced call vanish
  from the total, so a budget looked cheaper than reality. Records with no
  currency are now counted as unknown; records in a different currency are
  still left out, because those are genuinely unrelated.
- Milestone 10: `ProviderAuth`. **No provider is eligible for native login**:
  `capabilities` reports `native_login: false` with `reason: "not_reviewed"` and
  `begin` refuses, because the review registry ships empty on purpose and the
  plan states that a private repository does not by itself satisfy a provider's
  requirements. Behind the closed gate: one-use random state, PKCE with S256,
  exact loopback redirect matching, a ten minute expiry, a local `0600` store,
  and an exchange that happens on the user's machine and tells the coordinator
  nothing. Anthropic stays on an API key or its official binary, and CSHCLI
  never reads or exports Claude.ai tokens. See [providers](docs/PROVIDERS.md).
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
- The first run no longer needs a second terminal, four invocations of `start` or
  a running `serve` before anything works.
- Removed explanatory comments and docstrings from production code, tests and
  maintenance scripts to restore the repository's owner style rule. Executable
  multiline strings such as SQL schemas and child-process source remain data.
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
- **581 tests pass**, with 5 explicit skips: two symbolic-link cases, two real
  PostgreSQL cases, and one POSIX permission case on Windows.
- **CI is active** and green on Windows and Linux with Python 3.11, 3.12 and
  3.13.

### Notes
- This is an alpha pilot. The remote multi-user service and sandboxed arbitrary
  execution remain in the superplan. The mediated runner, local integration
  queue and deployment coordination exist, but no remote worker or cloud
  destination has been exercised.
- The `Workspace` boundary is a filesystem boundary, not a sandbox. It does not
  constrain an arbitrary command running inside the workspace.

## [0.3.0] - 2026-10-15

Reaching something useful used to take four commands and an environment
variable, and a provider key lived in the shell history and in every child
process an agent spawned. This release makes the first run say what is
missing, keeps keys out of the environment, reports on updates instead of
applying them, and proves that a restore reproduces the state without winding
the fence backwards.

### Added
- `scripts/restore_drill.py`: backs up the pilot database, restores it into an
  **empty** database, verifies it, and then proves that a second restore onto
  the same target is refused. The property it checks hardest is that **the
  fence never goes backwards**: a backup that preserved row counts but rolled
  the fence back would look perfect and be dangerous, because an agent from
  before the backup would validate again. The PostgreSQL version of the same
  three checks is now a rehearsal rather than a guess.
- `cshcli serve --remote` checks a remote configuration and **refuses to
  start** without TLS and a PostgreSQL DSN, and never reports itself started
  when it did not.

### Fixed
- The personal data guard took any dotted decorator for a possible email
  address, which blocked two commits. It was not weakened: the tests were
  rewritten, because relaxing a security control so your own code passes it
  stops it protecting anything.
- The provider capture test required a 200 ms timeout to return in under
  800 ms, with no margin for starting two interpreters on a busy machine. It
  now allows 2.5 s, which still proves the parent was not waited out.

## [0.2.0] - 2026-10-15

The coordination layer grew past the point where "local pilot" described it
honestly. This release closes the runner, the task DAG, the integration queue,
deployments and budgets; it fixes the personal data guard, which had been
reading the working tree instead of the index; and it adds the plan for
running online and for a first run that needs no instructions.

### Security
- The personal data guard read the **working tree** instead of the staged
  index. `committed_text` built the git spec as `f"{revision}:{name}"`, which
  for the index revision produced `::name`; git rejects that, and the code
  silently fell back to the file on disk. A file edited after `git add` was
  therefore judged on text that was never committed, while the staged text
  went to the remote unexamined. It now reads the index and fails closed
  instead of substituting something else.
- A timeout during a deployment's **health check** escaped as an unhandled
  exception rather than moving the deployment to `reconciling`. Only the change
  itself was protected. A destination with a real socket in it is what found it.
- Usage totals filtered by currency in SQL, so a call with no price vanished
  from the total and a budget looked cheaper than reality. Records with no
  currency are now counted as unknown; records in another currency are still
  excluded, because those are genuinely unrelated.
- `Personal data guard` is a **required** status check, `main` cannot be force
  pushed or deleted, and every change arrives through a pull request.

### Added
- A mediated `Runner`: `read_file`, `write_file`, `remove`, `rename`. Every
  write validates its lease at the moment the bytes move, a lost heartbeat
  ends the run, and no method executes a command.
- `Store.validate_lease` and `Client.validate_lease`/`renew_lease`.
- `Identity`: expiring sessions stored only as HMAC-SHA256, revocation scoped
  per member or agent, and an authorization generation that refuses work
  queued before a revocation.
- `TaskService`: seven task states, dependency cycles refused on create and on
  modify, and a `claim` that acquires leases in the same transaction that marks
  the task running.
- `IntegrationQueue`: one integration per project, a dedicated worktree, the
  base recomputed for a second patch, checks on the composed result, and a
  compare-and-swap that advances the branch only if it had not moved.
- `DeployService` and `DeployWorker`: per-artefact idempotence enforced by a
  database constraint, approval bound to the artefact digest, and a rollback
  refused when the environment moved.
- `ProcessDestination`: a destination whose state is written by a separate
  process and whose health is a real HTTP socket, so the four acceptance checks
  run against something that fails the way a real one fails.
- `ProviderAuth`: PKCE, one-use state and a local store behind an eligibility
  registry that ships **empty**. No provider is eligible; the review the plan
  requires has not been done.
- `Usage` and `BudgetPolicy` with `Decimal`, refusing any cost without a
  currency or a price date, and never turning an unknown into zero.
- `RemoteStore` for PostgreSQL, with row-locked acquisition and a refusal to
  serve traffic while unverified, plus `migrations/001_remote.sql`,
  `deploy/compose.yaml` and `docs/OPERATIONS.md`.
- `docs/PLAN-ONLINE.md`: the plan for running online, for a first run that
  needs no instructions, and for an update that reports before it changes
  anything. Nothing in it is implemented yet.
- `scripts/release.py`: builds the wheel, writes `SHA256SUMS`, and verifies
  the **installed** copy rather than the working tree. It does not sign or
  publish, and it says so.

### Known limits, unchanged
- **No sandbox.** The workspace is a path boundary and the runner mediates
  every write. There is no CPU, memory, process or network limit, and no
  arbitrary execution.
- **No remote service in use.** The PostgreSQL store, its migration and its
  operations manual exist and the store refuses to serve while unverified, but
  no server has been run and the concurrency drill has not been executed.
- **No real deployments.** The coordination is complete and its four
  acceptance checks pass against a real process, but no provider is configured
  and nothing has been published anywhere.
- **No chaos drills, no proven restore, no signed release.**
- **One reviewer.** `CODEOWNERS` names the owner and the ruleset does not
  enforce code owner review, so there is no second pair of eyes by design.
- **The built web is not published**, by decision of the owner.

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
