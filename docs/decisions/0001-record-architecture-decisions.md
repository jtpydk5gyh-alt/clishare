---
status: accepted
date: 2026-10-14
deciders: jtpydk5gyh-alt
consulted: []
informed: []
---

# Record architecture decisions

## Context and problem statement

CSHCLI ships as a public repository with a single owner and no formal way to
record why a structural choice was made. Choices about process, layout, and
protocol are currently recoverable only from commit history and chat, which
does not survive a handoff or a new contributor. The superplan anticipates a
growing set of decisions that must outlive any single release, so the project
needs a lightweight way to capture context, options, and consequences without
adding a tool or a service.

## Decision drivers

- Decisions must outlive the person and the release that produced them.
- The format must be plain Markdown plus YAML front matter so it stays in the
  repository and readable without any dependency.
- The overhead per decision must stay low enough that writing one is cheaper
  than re-deriving the reasoning later.
- The pilot has one active reviewer, so the record cannot depend on a review
  quorum to be useful.

## Considered options

- MADR 3.0, the Markdown Any Decision Records format.
- Conventional Commits only, with no separate record.
- An architecture wiki outside the repository.
- A dedicated decision-log tool or service.

## Decision outcome

Chosen option: **MADR 3.0**, because it is plain files, keeps the decision
next to the code, supports incremental adoption by numbering decisions, and
degrades to plain Markdown if the project ever stops using it.

Every decision gets one file at `docs/decisions/NNNN-short-title.md` with YAML
front matter carrying `status`, `date`, `deciders`, `consulted`, and
`informed`, followed by the MADR headings: Context and problem statement,
Decision drivers, Considered options, Decision outcome, Consequences, Pros and
cons of the options, and Links.

A decision is accepted, superseded, or deprecated. Superseding a decision means
adding a new file that links back to the one it replaces and changing that
one's status; files are never deleted or rewritten in place.

## Consequences

- Good, because the reasoning behind each structural choice becomes
  searchable and reviewable in the repository.
- Good, because new contributors can see why the project looks as it does
  without archaeology.
- Good, because the cost of adding one is a single file with no tooling.
- Bad, because writing a record is a small tax on every structural change and
  will be skipped more than once.
- Bad, because the log only stays useful if the owner keeps linking decisions
  to the code they affect.

## Pros and cons of the options

### MADR 3.0

- Good, native Markdown with optional front matter and no new dependency.
- Good, incremental: each decision is an independent numbered file.
- Good, encodes status and supersession, so history is preserved.
- Bad, the format itself is not machine-checked, so structure drifts over time.

### Conventional Commits only

- Good, already part of the commit workflow, so it costs nothing extra.
- Bad, a commit message has no place for context, drivers, or alternatives.
- Bad, reverts, rebases, and merges make the surviving record noisy.

### An architecture wiki outside the repository

- Good, supports browsing by topic and richer authoring tools.
- Bad, splits the project across two systems that can drift apart.
- Bad, the wiki becomes inaccessible when access to the platform is lost.

### A dedicated decision-log tool or service

- Good, can validate format and index decisions automatically.
- Bad, adds setup, hosting, and a second thing to maintain for one owner.
- Bad, the record is no longer in the repository, so review loses its context.

## Links

- Superplan: [docs/superpowers/plans/2026-10-14-cshcli.md](../superpowers/plans/2026-10-14-cshcli.md)
- Design: [docs/superpowers/specs/2026-10-14-cshcli-design.md](../superpowers/specs/2026-10-14-cshcli-design.md)
- Continuous integration notes: [docs/ci.md](../ci.md)