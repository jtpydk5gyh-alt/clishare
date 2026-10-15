# Operations

How to run the remote coordinator, and what has to be true before you let a
real user near it.

## What is verified today, and what is not

| Area | State |
| --- | --- |
| Sessions, expiry and revocation | Verified locally |
| Mediated writes and the publication gate | Verified locally |
| PostgreSQL storage | **Not verified.** No server has been run |
| Eleven concurrent processes against a real database | **Not verified.** The test exists and skips |
| HTTPS deployment, private network, restore drill | **Not verified.** No deployment has been made |

`RemoteStore.verification()` returns this same answer at runtime, and
`RemoteStore.assert_production_ready()` refuses to serve traffic while it says
`unverified`. The point is not ceremony: the plan's acceptance criterion for
the distributed version is that it does not advertise guarantees that have not
passed their tests, and the cheapest way to keep that promise is to make the
code unable to break it silently.

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
psql "$CSHCLI_REMOTE_DSN" -f migrations/001_remote.sql
```

Two choices in that file are not portable and must not be "simplified":

- **Fences come from a sequence.** A per-row counter can be rewound by a
  restore, handing an old holder a fence that still looks current.
- **Acquisition locks the project row.** Resources that overlap by prefix can
  sit in different rows, so checking only colliding rows does not serialise
  the decision. `SELECT id FROM projects WHERE id = %s FOR UPDATE` makes every
  acquisition in a project one at a time.

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