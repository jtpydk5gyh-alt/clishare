# Operations

How to run the remote coordinator, and what has to be true before you let a
real user near it.

## What is verified today, and what is not

| Area | State |
| --- | --- |
| Sessions, expiry and revocation | Verified locally |
| Mediated writes and the publication gate | Verified locally |
| PostgreSQL storage | **Verified** against a real server: 16.2, nine application tables plus the `schema_migrations` ledger, migration applied and the schema checked afterwards |
| Eleven concurrent processes against a real database | **Verified.** The test runs, and exactly one of eleven processes wins |
| Restore into an empty database | **Verified** with `pg_dump` and `pg_restore`: row counts match, restoring over a populated database is refused, and the fence never goes backwards |
| HTTPS | **Verified on loopback** with a self-signed certificate: the server starts, answers `/healthz` over TLS and refuses plain HTTP |
| Two machines, two accounts | **Not verified.** That needs a second machine |
| Public trust chain | **Not verified.** The certificate is self-signed and a client has to trust it explicitly |

`RemoteStore.verification()` still answers `unverified`, because the criterion
it encodes — eleven *machines* — has not been met. `assert_production_ready()`
keeps refusing, and that is deliberate: proving that a row lock works is not the
same as proving the service is safe to expose.

## Running a real PostgreSQL without Docker

This machine has no Docker and no WSL distribution. `pip install pgserver`
brings the PostgreSQL 16.2 binaries, which is enough to run a real cluster:

```
pip install pgserver
python scripts/postgres_local.py start
```

It creates a cluster under `~/cshcli-pg/cluster`, listens on `127.0.0.1:55432`
and prints the DSN. `stop`, `dsn` and `destroy` do the obvious things. The
package is **infrastructure, not a dependency**: the pilot and the client stay
dependency-free.

`scripts/postgres_local.py` writes subprocess output to files instead of pipes.
On Windows the server process inherits an open pipe and the reader never
returns, which is what made an early version of the helper appear to hang.

## Install

The driver is an extra, never a runtime requirement. Installing `cshcli`
alone must not pull in a database driver the local pilot does not use.

```
pip install 'cshcli[remote]'
```

## Database

`deploy/compose.yaml` starts PostgreSQL with no published port: the only way
in is from the compose network.

```
POSTGRES_PASSWORD=... docker compose -f deploy/compose.yaml up -d
```

Set the password from your environment, never from a file in the repository.

Apply the schema once:

```
python scripts/migrate.py
```

It takes `CSHCLI_REMOTE_DSN`, applies every `migrations/*.sql` that is not a
rollback, and then **checks that the nine application tables are really
there**. A file
whose text contains `DROP` is refused outright: the migration and its rollback
are separate files on purpose, and mixing them is how a deploy ends up with no
schema at all.

Three choices in `migrations/001_remote.sql` are not portable and must not be
"simplified":

- **Fences come from a sequence.** A per-row counter can be rewound by a
  restore, handing an old holder a fence that still looks current.
- **Acquisition locks the project row.** Resources that overlap by prefix can
  sit in different rows, so checking only colliding rows does not serialise the
  decision. `SELECT id FROM projects WHERE id = %s FOR UPDATE` makes every
  acquisition in a project one at a time.
- **Timestamps are `DOUBLE PRECISION`, never `REAL`.** `REAL` in PostgreSQL is
  `float4`, which keeps seven significant digits. A Unix instant in this
  century needs thirteen, so a lease expiring in 60 seconds was rounded to the
  nearest 128 seconds and stayed alive for minutes. SQLite's `REAL` is a
  double, which is why the pilot never saw it.

## Serving over TLS

```
python scripts/tls_certificate.py ~/cshcli-tls
$env:CSHCLI_REMOTE_DSN = "postgresql://cshcli@127.0.0.1:55432/cshcli"
$env:CSHCLI_TLS_CERT  = "$HOME/cshcli-tls/cert.pem"
$env:CSHCLI_TLS_KEY   = "$HOME/cshcli-tls/key.pem"
python scripts/cshcli.py serve --remote --port 55440
```

It binds, wraps the socket in TLS and answers `/healthz` with the real database
state. Plain HTTP on the same port is refused, and a client that does not trust
the certificate is rejected at the handshake.

**What this is not.** The certificate is self-signed and lives 30 days. A
browser or another machine will not trust it without being told to. Before
anyone outside this machine connects, replace it with one from a real
authority, or terminate TLS in front of the service.

## Before inviting anyone

Run these three and keep the output. They are the acceptance criteria, not
ceremonies.

1. **Concurrency.** `python -m unittest tests.test_remote_postgres` against a
   real server. Eleven independent processes race for `file:src` and
   `file:src/a.py`; exactly one must win. The test refuses to be replaced by a
   mock, because a mock proves nothing about row locks.
2. **Isolation.** Two machines, two accounts, two projects. Cross access is
   rejected every time, a revoked session stops working, concurrent
   compare-and-set has one winner, and a killed worker releases its TTL.
3. **Restore.** Take a backup, drop the database, restore into an empty one,
   and confirm the row counts and that a fence from before the restore is still
   lower than every fence after it.

Only after those three does `assert_production_ready` stop refusing. It does
not currently, and that is the correct state of the code, not a defect.

## Migration from SQLite to PostgreSQL without two authorities

The rule is that there is never a moment when two writers exist.

1. Stop the local coordinator. Confirm nothing is listening.
2. Take the final SQLite backup and record the fence high-water mark.
3. Import into PostgreSQL **offline**, with the remote service stopped.
4. Start the remote service. Point the client at it.
5. Keep the SQLite file read-only for one release cycle, as a rollback target.

To go back: stop the remote service, point the client at the SQLite file,
restart locally. The reverse direction needs the same offline rule.

## Rollback

`migrations/001_remote.sql` ends with the statements that drop everything. Run
them only against a database you are willing to lose. To roll back a code
change without rolling back the schema, deploy the previous version; the
schema is additive and this repository has not yet shipped a destructive
migration.

## Backups

```
docker compose -f deploy/compose.yaml exec db pg_dump -U cshcli cshcli > backups/$(date -u +%Y%m%dT%H%M%SZ).sql
```

Restore into an **empty** database, never over a live one. A restore that
lands on a populated database is how two authorities come into existence.

### The pilot database, drilled for real

The PostgreSQL drill above cannot run here. The pilot's SQLite one can, and
it has been run:

```
python scripts/restore_drill.py --db .cshcli/coordinator.sqlite3
```

It backs up, restores into an empty database, verifies, and then tries again
to prove that a second restore onto the same target is **refused**. It checks
the property that matters most: **the fence never goes backwards**. A backup
that preserved row counts but rolled the fence back would look perfect and be
dangerous, because an agent from before the backup would validate again.

The same three checks — reproduce the state, keep the fence, refuse a
populated target — are the recipe for the PostgreSQL drill. Having run them
once here means the PostgreSQL version is a rehearsal, not a guess.

## Logs

Never log prompts, tokens or provider keys. The coordinator logs request IDs,
project, task, agent, lease and fence, which is enough to follow a decision
without exposing what was decided about.
