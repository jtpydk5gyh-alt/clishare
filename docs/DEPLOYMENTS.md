# Deployments

CSHCLI coordinates one artefact into one environment at a time, and it can
name exactly which artefact an environment serves. This document states what is
implemented, what is not, and why the difference matters.

## The honest summary first

**No concrete deployment destination is configured.** There is no staging
target, no registry, no provider account and no credential. Nothing in this
repository publishes anything to a third party.

`cshcli deploy reserve` is **still only a reservation**. It takes an exclusive
`deploy:ENVIRONMENT` lease and nothing else. It does not build, publish, promote
or verify. Its help text and its output say so, and that has not changed.

What exists is the part that decides *whether* a change may happen, the part
that records what happened, and the part that recovers when the destination is
ambiguous. Two destination implementations exist and neither is a deployment
target: `InProcessDestination`, an in-process object used by most tests, and
`ProcessDestination`, which writes state from a separate interpreter process and
answers health over a real HTTP socket. Neither may be described as a provider.

## What has been exercised

Every claim below is backed by a test in `tests/test_deploy.py` and runs
against a real SQLite database in a real temporary directory.

- The same idempotency key with the same payload returns the same deployment.
  The same key with a different payload is refused with `409
  idempotency_conflict`. The uniqueness is a database constraint on
  `(project_id, environment, idempotency_key)`, not a Python check.
- An approval is bound to the immutable set: project, environment, commit SHA,
  artefact digest and policy revision. Approving after the digest moved is
  refused with `409 approval_binding_changed`. Approving without the owner role
  is refused.
- Permission, authorization generation, the checks SHA, the digest and the
  approval are checked twice: once before the deployment moves to `running`,
  and again immediately before the external effect. A revocation that lands
  between the two stops the change.
- Eleven workers racing one environment produce exactly one change.
- An ambiguous timeout moves to `reconciling` and never to a retry. The worker
  reads the destination's state before considering anything else.
- A failed health check moves to `failed` and never to `healthy`, and the
  previous digest is restored under the same environment control.
- A late rollback of A does not undo B once B is healthy.
- A destination that cannot decide stays `unknown` and promotions stop for that
  environment.

## The four acceptance checks, now run

The four checks are executed in `tests/test_deploy_process.py`, against
`ProcessDestination` in `src/cshcli/process_destination.py`: a destination whose
state is written by a **separate interpreter process** into a directory, and
whose health is a **real HTTP request** to a localhost server.

| Check | How the failure is induced |
| --- | --- |
| Staging deploy | The worker changes an environment served by a process that outlives it |
| Induced health failure | The health server is **stopped**, so the failure is a refused connection |
| Rollback | The environment row is read, then the rollback is conditioned on it |
| Idempotent re-send | The same key and the same payload are sent again |

A fifth failure is induced by a socket that **accepts the connection and never
answers**, which is a timeout rather than a refusal. That one found a real bug.

### What the real destination found

`DeployWorker._start` caught `DestinationTimeout` around `promote` but called
`destination.health(...)` unprotected. A timeout during the health check
therefore escaped as an unhandled exception instead of moving the deployment to
`reconciling`, which is precisely the outcome this milestone exists to prevent:
the environment may well have served the artefact and lost the answer on the way
back, and treating that as a plain failure lets the next attempt overwrite a
deployment that actually landed.

The in-memory destination could never have found this. Its `health` returns a
dictionary and never raises. It took a destination with a real socket in it.

The same gap existed in `_reconcile`, where a timeout during reconciliation's
health check now leaves the deployment in `reconciling` instead of crashing.

### What still needs an account

`ProcessDestination` is not a cloud provider and must not be described as one.
It writes a directory and answers on localhost. What remains unverified is
anything that needs credentials: a real provider, secrets per environment, and
an environment shared by more than one machine. The four checks above are the
plan's acceptance line and they now pass against a process that fails the way
real destinations fail; they are not a substitute for a provider rollout.

## What has not been exercised

- **No staging deploy was run.** There is no destination to run it against.
- **No induced health failure on a real target.** The health failure is
  induced on `InProcessDestination`.
- **No rollback was performed against a real target.**
- **No idempotent re-send was verified against a provider API.**
- **No production approval policy is configured.** Approval is uniformly
  required, and every approval is the project owner's.
- **No provider was contacted.** There is no network call anywhere in this
  milestone.

## What has not been exercised

- **No staging deploy was run.** There is no destination to run it against.
- **No induced health failure on a real target.** The health failure is
  induced on `InProcessDestination`.
- **No rollback was performed against a real target.**
- **No idempotent re-send was verified against a provider API.**
- **No production approval policy is configured.** Approval is uniformly
  required, and every approval is the project owner's.
- **No provider was contacted.** There is no network call anywhere in this
  milestone.

The checks above run against a local process and a localhost socket. They prove
the coordination survives a destination that fails for real reasons. They do
not prove anything about a third-party provider, which has never been
contacted.

## The states

`queued`, `awaiting_approval`, `running`, `reconciling`, `unknown`, `healthy`,
`failed`, `rolled_back`.

The two that carry the most weight are the ones a binary status cannot
express. `reconciling` means the request reached the destination and the answer
was lost, so the worker must ask what the destination serves instead of
guessing. `unknown` means the destination could not answer that either, and the
environment refuses further promotions until a human resolves it.

Presenting either as a plain failure would let a blind re-run overwrite a
deployment that actually succeeded. That is the failure this milestone exists
to prevent, so the ambiguity is persisted rather than resolved optimistically.

## The digest is explicit

A deployment request names its artefact digest as `sha256:` plus 64 lowercase
hex characters, and names its commit as a 40 character SHA. There is no code
path that reads `HEAD`, a branch name, or any implicit "current" state at run
time. The workflow rejects a malformed SHA or digest before it reserves
anything.

The reason is that an implicit source makes the approval meaningless: an
approval would bind to whatever the repository happened to point at when the
worker ran, not to the thing a person reviewed.

## Idempotence

`DeployService.enqueue` takes an idempotency key scoped to one project and one
environment. The database refuses a duplicate key, and a duplicate whose payload
differs is refused with `409`. The same key with the same payload is the same
deployment, so a retried request is safe and produces no second change.

The destination is addressed with that same key as its external key, so a
destination that supports idempotence can absorb a duplicate.

## One worker per environment

The worker takes the existing `deploy:ENVIRONMENT` lease, which only the project
owner may take, and the fence from that acquisition is what travels with the
change. `InProcessDestination` refuses a fence that is not newer than the one it
already accepted for that environment, which is what a real destination's
external fencing would do.

Two workers cannot both change an environment because only one can hold the
lease. The other is refused.

## Rollback

`DeployWorker.rollback` is conditioned on three values the caller read before
deciding: `expected_active_deployment_id`, `expected_digest` and
`environment_generation`. Any mismatch is refused with `409 stale_rollback` and
the state is left exactly as it was.

That is what stops a late rollback of A from undoing B. By the time the late
rollback arrives, B is active, so the environment no longer matches what the
caller remembered, and the refusal is the correct answer rather than an error to
work around.

A rollback also passes through permission, the environment lease reservation and
an audit event. It is a change to a live environment and is treated as one.

## The workflow

`.github/workflows/deploy.yml` uses a `concurrency` group keyed on project and
environment, with `cancel-in-progress: false`.

**That setting is not a FIFO guarantee.** GitHub does not promise that two runs
in the same group execute in the order they were queued, and it may reorder
them. The queue that decides what reaches an environment is CSHCLI's persistent
one in the coordinator database, not GitHub's. The workflow's concurrency group
reduces contention and makes the environment visible in the GitHub UI; it is
not what makes the ordering correct.

The workflow reserves the environment and stops there. It has no deployment
step, because there is no destination to deploy to and no HTTP route that
accepts a deployment request.

## Building a real destination

A real destination must implement the `Destination` protocol:

- `promote(change)` makes the environment serve `change.digest`. It must call
  `change.authorize()` immediately before acting; that call re-verifies
  permission, generation, checks SHA, digest, approval and the lease. It should
  pass `change.fence` and `change.external_key` to the provider so the provider
  can fence and deduplicate.
- `describe(external_id)` answers whether a change with that external
  identifier landed, and which digest is serving. Returning an undecided answer
  is correct and safe; guessing is not.
- `health(digest)` answers whether the environment serving that digest is
  healthy.

`promote` must raise `DestinationTimeout` when the answer is genuinely lost,
after recording whatever external identifier it obtained, so the worker enters
`reconciling` rather than retrying.

Until such an adapter exists and is verified against a real provider, this
milestone is a coordination and recovery mechanism, not a deployment system.

## Judgement calls

These decisions were not specified in the plan and are recorded here rather
than in code comments.

1. **Approval is required for every environment.** The plan leaves approval to
   a project policy that does not exist yet. Requiring it uniformly is the
   stricter reading, and it keeps a member from promoting anything.
2. **`checks_sha` must equal `commit_sha`.** The checks that ran for this
   artefact must be the checks of the requested commit. A mismatch is
   `checks_sha_mismatch`.
3. **A failed health check triggers a restore of the previous digest.**
   Recovering immediately is what the plan's step 11 describes. The restore runs
   under the same environment lease and emits its own audit events.
4. **The environment pointer is per project and environment**, in
   `deployment_environments`, with a generation that increments on every
   change. `expected_*` values in a rollback refer to it.
5. **The in-process destination lives in `deploy.py`.** The tests need a real
   working implementation and the project has no fixture directory convention
   for this. It is deliberately small and obviously not a target.