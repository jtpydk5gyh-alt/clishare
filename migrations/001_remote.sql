-- PostgreSQL schema for the remote coordinator.
--
-- Two choices here are load-bearing and are not portable to SQLite without
-- losing the property the plan asks for.
--
-- The fence comes from a single sequence, never from a per-row counter. A
-- per-row counter can be restored backwards by a backup restore, which would
-- hand an old holder a fence that looks current.
--
-- Acquisition takes a row lock on the project before it reads or inserts any
-- lease. Two resources that overlap by prefix can live in different rows, so
-- checking only the rows that collide is not enough to serialise the
-- decision: SELECT ... FOR UPDATE on the project makes every acquisition in
-- that project one at a time.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL DEFAULT extract(epoch FROM now())
);

CREATE TABLE IF NOT EXISTS memberships (
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    token_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    expires_at REAL NOT NULL,
    accepted_at REAL,
    created_at REAL NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS lease_fence_sequence AS BIGINT START WITH 1;

CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    resource TEXT NOT NULL,
    fence BIGINT NOT NULL DEFAULT nextval('lease_fence_sequence'),
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS leases_by_project ON leases(project_id, resource);

CREATE TABLE IF NOT EXISTS memory (
    project_id TEXT NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL,
    author_id TEXT NOT NULL REFERENCES users(id),
    updated_at REAL NOT NULL,
    kind TEXT,
    scope TEXT,
    status TEXT,
    source_commit TEXT,
    evidence_json TEXT,
    expires_at REAL,
    PRIMARY KEY (project_id, key)
);

CREATE TABLE IF NOT EXISTS authorization_grants (
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    scope TEXT NOT NULL,
    generation BIGINT NOT NULL DEFAULT 1,
    revoked_at REAL,
    PRIMARY KEY (user_id, project_id, scope)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS events_by_project ON events(project_id, created_at);

-- Rolling this back drops the remote schema entirely. The pilot's SQLite file
-- is a separate artefact and is never touched by this script; see
-- docs/OPERATIONS.md for the order that keeps one authority at a time.
DROP TABLE IF EXISTS events, sessions, authorization_grants, memory, leases,
    invitations, memberships, projects, users CASCADE;
DROP SEQUENCE IF EXISTS lease_fence_sequence;