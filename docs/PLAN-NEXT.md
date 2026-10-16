# Plan: what remains

Written on 17 October 2026 against `main` at `fd3bc96`, version 0.9.0, 73
commits, CI green on Windows and Linux across Python 3.11, 3.12 and 3.13.
That hash was the tip when this file was written, before the plan's own pull
request merged; verify with `git log -1`.

Three plans exist and all of their steps are closed except the ones written
here: `PLAN-ONLINE.md`, `PLAN-INFRA.md` and the eleven tasks of
`superpowers/plans/2026-10-14-cshcli.md`. This file does not replace them. It
answers one question: what is left, what each item unblocks, and who is
waiting on whom.

The honest headline: **the code is not the bottleneck.** What is left is one
decision by the owner and one piece of infrastructure this machine does not
have.

## 0. Nothing is half-finished

`main` builds, CI is green, the working tree is clean, there is one worktree,
no branch is waiting, and no test is failing. Nothing below requires finishing
half a thing.

## 1. Blocked on the owner: the signing key

**The only item that is waiting on a person, and that person is the owner.**

Everything else is already installed and proved. `minisign` 0.12 is in the
portable copy and was verified against the public key the project publishes.
`release.py` signs by itself, checks the signature was written, refuses under
`--require-signature`, and builds while warning when no key is present. The
whole flow was exercised with a throwaway key that was deleted afterwards.

```
CSHCLI_SIGNING_KEY=ruta\a\tu-clave.key  python scripts/release.py
```

**What it unblocks, in order.** A signed release. Publishing it. Then, and only
then, `cshcli update` exercised against something real instead of a network
double, which is the one product path in the online plan that has never run
against a real artefact.

**Why it is not decided here.** Creating a signing identity in someone's name
without their say-so is not a call an agent should make alone. It produces a
key pair whose private half would have to live outside every synced copy for
the rest of the project's life.

## 2. Blocked on a second machine: the last four proofs

These are one activity, not four. Getting a second machine, or one real host
anywhere, closes all of them. Until then `RemoteStore.verification()` returns
`unverified` and `assert_production_ready()` refuses to serve, which is the
criterion working, not a defect.

| # | Proof | Why one machine cannot show it |
| --- | --- | --- |
| 2.1 | Eleven **machines** race for one lease and exactly one wins | Eleven processes prove `SELECT ... FOR UPDATE` works. They do not prove anything about a network, a second connection pool, or clock skew between hosts. |
| 2.2 | A restore performed while the other machine serves traffic | `pg_restore` into an empty database is proven. Restoring under live traffic is a different problem and is the reason a backup schedule is written down. |
| 2.3 | Cross-tenant access refused over the real network | The routes refuse it in tests. Refusing it across two hosts is what matters, and it is the row the master plan's verification matrix still owes. |
| 2.4 | A public trust chain instead of a self-signed certificate | TLS is proven end to end with a self-signed certificate that expires in 30 days. That proves the path, not that a browser or a corporate proxy would trust it. |

**The cheapest way to close all four.** One cheap second host, reachable over
the network, with the release published. Nothing in the design needs more.

## 3. Documentation debt found on 17 October

Cheap, and it is in this file's own spirit: a document that lies is a defect.

- Three more present-tense false claims survived the first pass and the test
  that was written to catch them. `PLAN-ONLINE.md` still says the remote
  service "has not been stood up" and that raising PostgreSQL "remains
  pending"; `PLAN-INFRA.md` still says there is no `minisign` on this machine,
  when 0.12 is installed and verified. The patterns in `test_docs_truth.py`
  need to widen.
- This file, and the SHA inside it, will themselves go stale. The rule already
  written down applies: verify with `git log -1` rather than trusting a
  remembered hash.

## 4. Deliberate decisions, not tasks

These are closed by a decision, not by effort. Doing them anyway would be
reopening a choice the owner already made.

- **The sandbox does not exist.** No CPU, memory, process or network limits,
  and arbitrary execution stays unimplemented. The mediated runner validates
  the lease before every write, stops on heartbeat loss and has no method that
  runs a command. Building it needs a Linux container or VM with verified
  controls; a native Windows or macOS runner is not to be advertised as
  equivalent until those controls are verified.
- **The chat is read-only.** `/ver` reads and `/buscar` searches. Nothing
  writes from the conversation. The publication gate and the integration queue
  exist and are tested; connecting them to a chat means the writer is a model,
  and a model is not a person reviewing a diff.
- **`web/` is not published.** Ignored by git with the reason written next to
  it.
- **The native OAuth registry is empty on purpose.** A provider needs a review
  entry to become eligible, and a test asserts the registry is empty. That test
  is the only thing stopping a careless edit from enabling a login path.

## 5. Never exercised, and honestly so

Not defects. Named so that nobody reads "green" as "verified against the real
thing".

- **No AI provider has ever been contacted.** Provider tests use fixtures and
  mocks. No account, no quota, no spend, no billing path.
- **Nothing has been deployed anywhere.** Deploy coordination, idempotence and
  rollback run against a separate process and a real health socket, but no
  provider is configured and no environment exists.
- **No CA, no public certificate, no second host.** See section 2.
- **`cshcli update` never ran against a published release.** Blocked behind
  section 1.

## Order

1. The signing key, because it is one decision and it unblocks a release.
2. A second machine, which closes the four proofs and turns the online claim in
   the README into something that can be read.
3. The documentation debt above, whenever it is convenient; it needs no
   infrastructure at all.

Nothing else is queued. If the owner wants more work, the honest candidates are
the sandbox and the OAuth registry, and both are decisions before they are
tasks.
