# Releases

How a release is made here, and what it does not cover.

## What the script does

```
python scripts/release.py
```

It refuses rather than warns when it should:

- **Two different versions** between `src/cshcli/__init__.py` and
  `pyproject.toml` abort the build. A release with two versions is not
  reproducible.
- **A dirty working tree** aborts the build. A warning is the kind of thing
  that gets read once and then ignored.

Then it builds the wheel, writes `SHA256SUMS`, and verifies the **installed
copy** in a throwaway directory: it imports the modules, checks that the
version it reports is the one requested, and runs `--help` from the installed
copy rather than from the working tree. Testing the working tree would prove
nothing about the artefact.

## What it deliberately does not do

It does not sign anything, it does not publish anywhere, and it does not verify
the install on Linux, macOS or on Python versions other than the one running
it. Those need a machine and credentials that do not exist on the machine that
writes this file. A release procedure that claims otherwise is worse than one
that admits it, so the script prints the omission on every run.

Publishing is a manual step and stays manual while there is one owner.

## The release history

### 0.2.0 — 15 October 2026

The coordination layer grew past the point where "local pilot" described it
honestly. Runner, task DAG, integration queue, deployments and budgets all
landed; the personal data guard was fixed to read the index instead of the
working tree; and the online plan was written.

Full notes in the [changelog](../CHANGELOG.md).

Verified before tagging: 423 tests pass with 4 skipped and a real SQLite, real
HTTP and a real git repository in every case. The wheel installs and answers
`--help` on Python 3.12.10, Windows.

### 0.1.0 — 14 October 2026

The local pilot: loopback coordinator, SQLite, projects, roles, invitations,
CAS memory, leases with fences, the CLI and the CI.

## Verifying an artefact you did not build

```
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" cshcli-0.2.0-py3-none-any.whl
```

Compare with `SHA256SUMS`. A mismatch means the file is not the one this
repository produced, and it should not be installed.

Checksums say the artefact is intact. They do not say who published it, which
is why signing is listed as not done rather than quietly assumed.