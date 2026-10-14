---
status: accepted
date: 2026-10-14
deciders: jtpydk5gyh-alt
consulted: []
informed: []
---

# Use MADR for architecture decision records

## Context and problem statement

The project is moving from a private pilot to a public, full open-source
repository. We need a lightweight, Markdown-native format for recording
architecture decisions that is easy to read on GitHub, easy to author
without extra tooling, and recognised by the open source community.

## Decision drivers

- Decisions must live in version control next to the code they describe.
- The owner prefers minimal tooling and no comments in code; the same
  rule applies to documentation: keep prose dense and free of ornament.
- Reviewers must be able to read a decision without installing anything.
- The format must allow future decisions to supersede earlier ones.

## Considered options

- MADR (Markdown Any Decision Records) 3.0
- adr-tools (Bash) plus plain Markdown
- Lightweight custom format

## Decision outcome

Chosen option: "MADR 3.0", because it is Markdown-native, widely adopted
in OSS repositories, and its YAML front matter lets us capture status,
date, and deciders without bespoke tooling. Future decisions will follow
the same template; superseded ones will be marked with `status:
superseded` and a `superseded-by:` reference at the top.

### Consequences

- Good, because decisions are readable on GitHub and easy to author.
- Good, because the template is short and discourages prose bloat.
- Bad, because future tooling that processes ADRs (for example, an
  index generator) is not bundled; we will only add one if there is
  real value.

## Pros and cons of the options

### MADR 3.0

- Good, Markdown only, YAML front matter, recognised by the community.
- Neutral, no automatic numbering; we handle it via filename.

### adr-tools

- Good, automates numbering and links.
- Bad, requires a Bash tool and stores decisions outside `docs/`.

### Custom format

- Good, fully owned by the project.
- Bad, more maintenance; readers must learn yet another shape.

## Links

- https://adr.github.io/madr/
- https://github.com/joelparkerhenderson/architecture-decision-record