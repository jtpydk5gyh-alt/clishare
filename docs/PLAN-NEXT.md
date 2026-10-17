# Plan: what remains

Written on 17 October 2026 against `main` at `119587d`, version 0.9.0, 74
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

## 1. Done: the release is signed (publishing is still manual)

**The owner authorised the key on 17 October 2026 and it was created.** The
private key is password-protected and lives outside the repository; the public
key is committed at `cshcli-release.pub`, which is the only part that ever
leaves the machine.

`release.py` signs `SHA256SUMS` by itself, checks that the signature was
written, and refuses under `--require-signature` when no key is available, so
publishing unsigned is a refusal rather than a warning.

Checked in both directions, because a signature that cannot detect anything is
decoration: it verifies with the published key, a different real key is
rejected with a key-id mismatch, and changing one byte of `SHA256SUMS`
invalidates it.

```
CSHCLI_SIGNING_KEY=ruta\a\la-clave.key  python scripts/release.py
```

**What is left of it.** Publishing, which stays manual while there is one owner.
Then, and only then, `cshcli update` exercised against something real instead of
a network double, which is the one product path in the online plan that has
never run against a real artefact.

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

1. Publishing the signed release, which is manual while there is one owner. It
   unblocks `cshcli update` tested against a real artefact.
2. A second machine, which closes the four proofs and turns the online claim in
   the README into something that can be read.

Nothing else is queued. If the owner wants more work, the honest candidates are
the sandbox and the OAuth registry, and both are decisions before they are
tasks.
