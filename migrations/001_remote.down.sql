-- Rolling this back drops the remote schema entirely. The pilot's SQLite file
-- is a separate artefact and is never touched by this script; see
-- docs/OPERATIONS.md for the order that keeps one authority at a time.
DROP TABLE IF EXISTS events, sessions, authorization_grants, memory, leases,
    invitations, memberships, projects, users CASCADE;
DROP SEQUENCE IF EXISTS lease_fence_sequence;
