# Coordination HTTP protocol, version 1

Date: 15 October 2026. This version describes the local pilot. The server
prints the base URL; it will normally be `http://127.0.0.1:8765`. The service
only accepts loopback and must not be published through a tunnel, reverse
proxy, or public bind. HTTPS and verified accounts belong to a later phase.

## Conventions

- UTF-8 JSON. Bodies must be objects, with `Content-Type: application/json`.
- Maximum HTTP body: 1 MiB (1,048,576 bytes).
- Except for `GET /health` and `POST /v1/users`, every route requires
  `Authorization: Bearer <personal_token>`.
- `id` and `project_id` are opaque identifiers. Clients must not infer
  permissions from them.
- Times are UTC server timestamps expressed in Unix seconds. Clients do not
  control absolute expiration.
- JSON integers are strict: `true`, `1.0`, and `"1"` do not stand in for `1`
  in versions, fences, or TTLs.
- Memory is paginated by key; active leases are returned as a list. Events
  have a result limit; they are not a real-time subscription.
- Successful responses contain `{"data": ...}`; errors contain
  `{"error":{"code":"...","message":"..."}}`.
- Permissive CORS headers are not emitted. Requests with `Origin` and `Host`
  values that are not the local service are rejected to reduce exposure to
  web pages and DNS rebinding.

The examples use descriptive identifiers to show the shape of the JSON. The
server generates the real values.

## Health and local identity

### `GET /health`

No bearer. Response `200`:

```json
{"data":{"status":"ok","mode":"local-pilot"}}
```

### `POST /v1/users`

No bearer. Body:

```json
{"name":"ana"}
```

The name must be non-empty text, without control characters, and up to 80
characters. Names are unique case-insensitively. Response `201` with at
least:

```json
{"data":{"id":"user-id","name":"ana","token":"server-generated-secret"}}
```

The personal token is delivered at creation and stored as a hash in the
database. The client must keep it locally without adding it to the
repository. `409 name_taken` indicates a taken name. This identity is local:
it does not verify email, provider account, or GitHub user. The pilot does
not include token revocation or recovery.

## Projects and invitations

### `GET /v1/projects`

Bearer required. Response `200` with the list of projects the user belongs
to. Each entry includes `id`, `name`, and its `role`. Projects from other
identities are not listed.

### `POST /v1/projects`

Body `{"name":"my-project"}`. Name is non-empty text, without control
characters, up to 120 characters. Response `201` with the created project.
The creator takes the `owner` role.

### `POST /v1/projects/{project_id}/invites`

`owner` only. Optional body:

```json
{"role":"member","ttl":3600}
```

`role` accepts `member` and `viewer`; default `member`. `ttl` is an integer
from 1 to 604800 seconds; default 3600. Response `201` with the invitation
token and its expiration. Inviting as `owner` is not allowed. The service
stores the token hash and does not send email or messages to the guest.

### `POST /v1/invites/accept`

The recipient presents their personal bearer and this body:

```json
{"token":"invitation-token"}
```

Response `200`:

```json
{"data":{"project_id":"project-id","role":"member"}}
```

Acceptance and joining are atomic. Two clients consuming the same invitation
simultaneously leave a single winner. A consumed invitation returns
`409 invite_used`; an expired one returns `409 invite_expired`; an unknown
token returns `404 invite_not_found`. An acceptance does not downgrade the
role of an existing owner.

## Memory with expected version

### `GET /v1/projects/{project_id}/memory`

All members can read. Query parameters: `limit`, integer 1–10 (default 10),
and `after`, the last key of the previous page. Keys are sorted
lexicographically and the cursor is exclusive. Response `200` with a page:

```json
{"data":{"items":[
  {"key":"architecture","content":"Shared context","version":1,"author_id":"user-id","updated_at":1791943200.0}
],"next_cursor":null}}
```

Each entry includes `key`, `content`, `version`, `author_id`, and
`updated_at`; the project is fixed by the URL. If `next_cursor` is not
`null`, the next page is fetched with `?limit=10&after=<encoded-cursor>`. The
client must encode the cursor as a query value, not concatenate it without
escaping. Pagination is not a global snapshot: if keys are modified between
pages, the client must re-read before acting on the content.

### `PUT /v1/projects/{project_id}/memory`

`owner` and `member` only. Body:

```json
{
  "key":"architecture",
  "content":"Each task will be developed in its own worktree during the runner phase.",
  "expected_version":0
}
```

`key` is non-empty text, without controls, up to 200 characters. `content`
is text up to 256 KiB encoded in UTF-8. `expected_version` is an integer
from 0 to 2^63 - 2. `0` creates a key that does not exist; to update, supply
the current version. The `200` response returns the persisted entry with
incremented version and author. A mismatch returns `409 version_conflict`
without overwriting.

The correct sequence: read the version, reconcile the desired content, write
with that version, and on `409` re-read and decide. Do not automatically
substitute `expected_version` and resend the same content; that would lose
the other party's change.

There is no memory deletion or full revision history in v1. Memory is
collaborative content; it cannot grant permissions or authorise deployments.

## Resource leases

### `GET /v1/projects/{project_id}/leases`

All members can read. Response `200` with active leases; expired leases
neither block nor appear as active. Each record includes `id`,
`project_id`, `user_id`, `agent_id`, `resource`, `fence`, and
`expires_at`.

### `POST /v1/projects/{project_id}/leases`

`owner` and `member` can reserve files; only `owner` can reserve a
deployment environment. Body:

```json
{
  "agent_id":"ana-agent-1",
  "resources":["file:src/api.py","file:tests/test_api.py"],
  "ttl":120
}
```

`agent_id` is a 1–120 character label without controls under the
authenticated identity. It does not replace the bearer and is not an
autonomous identity. `ttl` accepts integers from 1 to 3600 seconds;
default 120. `resources` is a list of 1–100 resources without duplicates
or internal overlaps; each resource is up to 1024 characters. The `201`
response is a **list of leases**, one per resource; each row has its own
opaque text `id` and integer `fence`. The batch is acquired in a single
transaction: if any resource conflicts, none is granted.

```json
{"data":[
  {"id":"lease-a-id","project_id":"project-id","user_id":"user-id","agent_id":"ana-agent-1","resource":"file:src/api.py","fence":41,"expires_at":1791943320.0},
  {"id":"lease-b-id","project_id":"project-id","user_id":"user-id","agent_id":"ana-agent-1","resource":"file:tests/test_api.py","fence":42,"expires_at":1791943320.0}
]}
```

Values are illustrative: `id` identifies the lease and `fence` its
generation. A conflict returns `409 lease_conflict` and requires waiting,
reducing resources, or replanning. The lease is not granted re-entrantly
by repeating the same `agent_id`.

### Supported resources

| Syntax | Meaning | Conflicts |
| --- | --- | --- |
| `file:src/api.py` | Relative path | That path, its leased parents, and its descendants |
| `file:src` | Directory prefix | `file:src/api.py`, but not `file:src2/api.py` |
| `deploy:staging` | Exact environment | Another `deploy:staging` lease |

File paths use `/` and are compared with a conservative `casefold()`. The
service rejects `\`, absolute or drive paths, empty segments, `.` or `..`,
Windows reserved names, ambiguous space/dot suffixes, and the characters
`:`, `<`, `>`, `"`, `|`, `?`, `*`, and control characters. Environments
use 1–64 ASCII letters, digits, `_`, or `-`. This avoids ambiguous resources
in the protocol; it does not resolve symlinks or block filesystem writes.
`deploy:PROD` and `deploy:prod` are the same normalised resource;
`deploy:prod-eu` is different.

### `POST /v1/projects/{project_id}/leases/{lease_id}/renew`

Only the user that acquired the lease. Body:

```json
{"fence":41,"ttl":120}
```

`fence` must be a positive integer equal to that of the lease. `ttl` has
the same range and default as acquisition. Response `200` with the renewed
record. The new expiration is computed from the server clock; the fence is
preserved. An expired lease returns `409 lease_expired` and does not
revive; an incorrect fence returns `409 fence_mismatch`.

### `DELETE /v1/projects/{project_id}/leases/{lease_id}`

Only the user that acquired the lease. **It carries a JSON body**:

```json
{"fence":41}
```

Response `200`: `{"data":{"released":true}}`. An incorrect fence or an
expired lease returns `409`. Another member cannot release the lease even
if they know its identifier and fence. Using a lease from another project
returns `404`.

Fences increase persistently with new acquisitions and survive restarts.
The client does not compute them. The integration queue protects the branch
update with a compare-and-swap against the SHA observed before checks. The
service still does not run arbitrary agent commands or publish cloud
deployments.

## Local Git integration queue

The queue is local-only. A `writer` or `owner` can submit and process entries;
a `viewer` can list and read them. Only the `owner` may name a repository or
branch in a request; a non-owner doing so receives
`403 repository_override_forbidden`. The repository otherwise comes from
`CSHCLI_REPOSITORY`. A request without a configured repository fails with
`409 repository_not_configured` instead of guessing a directory.

Before starting the coordinator, the operator must configure the check command
as a JSON array. It is executed without a shell in the dedicated integration
worktree, with a 240-second timeout:

```powershell
$env:CSHCLI_INTEGRATION_CHECK = '["python","-m","unittest","discover","-s","tests"]'
```

Processing a non-empty queue without this setting fails with
`409 checks_not_configured` and leaves the branch untouched. An invalid JSON
array fails with `500 integration_check_invalid`.

### `POST /v1/projects/{project_id}/queue`

Body:

```json
{
  "commit_sha":"40-hex-commit",
  "base_sha":"40-hex-base",
  "task_id":"optional-task-id",
  "repository":"optional-local-path"
}
```

Response `201` with the queue entry. Repeating the same commit in the same
project returns the original entry. A missing commit returns
`404 commit_not_found`. A commit the publication gate never accepted returns
`409 patch_not_accepted`.

### `GET /v1/projects/{project_id}/queue`

Response `200` with `{"data":{"entries":[...]}}`. Reading the queue does not
require repository or check configuration.

### `GET /v1/projects/{project_id}/queue/{entry_id}`

Response `200` with that project's entry. An identifier belonging to another
project is returned as `404 queue_not_found`.

**Publication gate.** A queue entry requires a prior accepted-patch record for
the same project and commit. `IntegrationGate.accept_patch` validates
authorization generation, lease fences and resources, and the queue refuses
anything it did not accept. A commit that no gate accepted returns
`409 patch_not_accepted`; a commit accepted with a different base returns
`409 patch_base_mismatch`. Acceptance is rechecked immediately before the merge,
so a record withdrawn while the entry waited is refused rather than merged.

### `POST /v1/projects/{project_id}/queue/next`

The owner may provide `repository` and `branch`; otherwise the configured
repository and the `integration` branch are used. An empty queue returns
`{"data":{"state":"idle"}}`. A successful composition returns state
`merged`; a conflict returns `review`; a failing check returns `failed`.
The branch advances only when its observed SHA still matches after checks.

## Events

### `GET /v1/projects/{project_id}/events`

All members can query the project's events. Response `200` with records
that include the project, actor, `kind`, payload, and timestamp. For
example, `memory.updated` indicates an accepted mutation. Events do not
contain bearer tokens, invitation tokens, API keys, or the full memory
content.

The store accepts `list_events(user_id, project_id, limit=100)` with an
integer limit from 1 to 1000. Exposing filters, cursors, and streaming over
HTTP will be added as an explicit extension; v1 does not promise to resume
a subscription from a cursor.

## Errors and retry rules

| HTTP | Situation | Client action |
| --- | --- | --- |
| `400` | Invalid JSON, field, type, resource, TTL, fence, duplicate `Content-Length`, or unsupported `Transfer-Encoding` | Fix the request; do not retry the same one |
| `401` | Missing, invalid, or unknown bearer identity | Select a valid local credential |
| `403` | Not a member, insufficient role, foreign lease, rejected Origin/Host | Change permissions or destination explicitly |
| `404` | Missing route, project, invitation, lease, commit, or queue entry | Re-read identifiers; do not create implicit substitutes |
| `409` | CAS, busy resource, fence, expiration, consumed invitation, missing repository/check configuration, or a patch the gate did not accept | Re-read state and replan |
| `413` | Body over 1 MiB | Reduce the body before resending |
| `415` | Body with a `Content-Type` other than `application/json` | Send JSON with the correct header |
| `500` | Unexpected internal failure | Preserve context, check the coordinator, and re-read before repeating mutations |

Example error:

```json
{"error":{"code":"version_conflict","message":"The memory version has already changed."}}
```

The `message` text is explanatory; clients decide with `code` and HTTP.
Internal SQLite details and secrets are not returned. The client accepts
responses up to 32 MiB and returns `response_too_large` if that limit is
exceeded, without trying to interpret truncated JSON. There is no general
idempotency key for POST in the pilot: after losing a response, the state
must be read before repeating a mutation. In particular, repeating an
acquisition may collide with the lease granted by the first attempt.

## Compatibility and guarantees

The `/v1` prefix identifies this contract. Adding response fields is
backwards compatible; removing fields, changing resource semantics, or
modifying roles requires versioning and migration. Clients must ignore
extra fields and treat identifiers as opaque.

v1 guarantees transactional coordination decisions and local Git queue
integration for a local coordinator. **It does not guarantee exclusion of
external writers, agent process isolation, multi-host Git integration, or real
serialised cloud deployments.** Those guarantees have
their own acceptance criteria in the
[design](superpowers/specs/2026-10-14-cshcli-design.md) and the
[plan](superpowers/plans/2026-10-14-cshcli.md).
