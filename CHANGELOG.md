# Changelog

All notable changes to CSHCLI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it leaves alpha.

## [Unreleased]

### Added
- English translation of every project document.
- Clean orphan history on `main`; the previous Spanish and personal-rule
  commits are retired.
- `AGENTS.md` is kept locally on the owner's machine only; it is added to
  `.gitignore` so it never reaches the public remote.
- This `CHANGELOG.md`, an `.editorconfig`, and a `.gitattributes` to
  standardise line endings and binary handling.

### Changed
- README, PLAN, USAGE, STATUS, REVIEW, PROTOCOL, OPEN_SOURCE, the
  superplan, and the design spec are now written in English.
- `docs/ESTADO.md` was renamed to `docs/STATUS.md`.
- `docs/REVISION.md` was renamed to `docs/REVIEW.md`.

### Notes
- This is an alpha pilot. The remote multi-user service, the isolated
  runner, automatic worktrees, the integration queue, and real
  deployments remain in the superplan and have not been delivered.
- CI is not yet activated; the template lives at
  `docs/templates/ci.yml.example` and will move to
  `.github/workflows/ci.yml` once the workflow publish permission is
  available on the public remote.

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
