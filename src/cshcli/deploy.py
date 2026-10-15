from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from typing import Callable, Protocol

from .errors import DomainError
from .store import Store, _resource, _text


QUEUED = "queued"
AWAITING_APPROVAL = "awaiting_approval"
RUNNING = "running"
RECONCILING = "reconciling"
UNKNOWN = "unknown"
HEALTHY = "healthy"
FAILED = "failed"
ROLLED_BACK = "rolled_back"

STATES = (QUEUED, AWAITING_APPROVAL, RUNNING, RECONCILING, UNKNOWN, HEALTHY, FAILED, ROLLED_BACK)
SETTLED = (HEALTHY, FAILED, ROLLED_BACK)

DEFAULT_POLICY_REVISION = "deploy-policy-1"

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

_EVENT_KINDS = {
    RUNNING: "deploy.running",
    HEALTHY: "deploy.healthy",
    FAILED: "deploy.failed",
    RECONCILING: "deploy.reconciling",
    UNKNOWN: "deploy.unknown",
    ROLLED_BACK: "deploy.rolled_back",
}


class DestinationTimeout(Exception):
    def __init__(self, external_id: str | None = None):
        super().__init__("The destination did not answer before the timeout.")
        self.external_id = external_id


class ArtifactChange:
    def __init__(self, project_id: str, environment: str, digest: str, deployment_id: str,
                 fence: int, external_key: str, authorize: Callable[[], dict]):
        self.project_id = project_id
        self.environment = environment
        self.digest = digest
        self.deployment_id = deployment_id
        self.fence = fence
        self.external_key = external_key
        self.authorize = authorize


class Destination(Protocol):
    def promote(self, change: ArtifactChange) -> dict: ...

    def describe(self, external_id: str) -> dict: ...

    def health(self, digest: str) -> dict: ...


class InProcessDestination:
    def __init__(self):
        self.active: dict[str, str] = {}
        self.external: dict[str, str] = {}
        self.promotions: list[dict] = []
        self.restores: list[dict] = []
        self.failing_digests: set[str] = set()
        self.timing_out_digests: set[str] = set()
        self.undecidable: set[str] = set()
        self._fences: dict[str, int] = {}
        self._sequence = 0

    def promote(self, change: ArtifactChange) -> dict:
        change.authorize()
        held = self._fences.get(change.environment)
        if held is not None and change.fence <= held:
            raise DomainError(409, "stale_fence",
                              f"{change.environment} already accepted fence {held}; {change.fence} is stale.")
        self._fences[change.environment] = change.fence
        self._sequence += 1
        external_id = f"{change.environment}-{self._sequence}"
        self.active[change.environment] = change.digest
        self.external[external_id] = change.digest
        self.promotions.append({"environment": change.environment, "digest": change.digest,
                                "external_id": external_id, "fence": change.fence,
                                "deployment_id": change.deployment_id})
        if change.digest in self.timing_out_digests:
            raise DestinationTimeout(external_id)
        return {"external_id": external_id, "digest": change.digest, "fence": change.fence}

    def describe(self, external_id: str) -> dict:
        if not external_id or external_id in self.undecidable:
            return {"decided": False, "digest": None, "external_id": external_id}
        digest = self.external.get(external_id)
        if digest is None:
            return {"decided": False, "digest": None, "external_id": external_id}
        return {"decided": True, "digest": digest, "external_id": external_id}

    def health(self, digest: str) -> dict:
        if digest in self.failing_digests:
            return {"healthy": False, "detail": "The health endpoint did not answer."}
        return {"healthy": True, "detail": "The health endpoint answered."}


class DeployService:
    def __init__(self, store: Store, policy_revision: str = DEFAULT_POLICY_REVISION,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.policy_revision = policy_revision
        self.clock = clock

    def enqueue(self, actor_id: str, project_id: str, environment: str, commit_sha: str,
                artifact_digest: str, idempotency_key: str) -> dict:
        environment = _environment(environment)
        commit_sha = _sha(commit_sha, "commit_sha")
        artifact_digest = _digest(artifact_digest, "artifact_digest")
        idempotency_key = _text(idempotency_key, "idempotency key", 200)
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, actor_id, project_id, write=True)
            fingerprint = _fingerprint(project_id, environment, commit_sha, artifact_digest,
                                      self.policy_revision)
            existing = connection.execute(
                "SELECT * FROM deployments WHERE project_id = ? AND environment = ? AND idempotency_key = ?",
                (project_id, environment, idempotency_key)).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    raise DomainError(409, "idempotency_conflict",
                                      "This idempotency key already names another artefact.")
                record = self._load(connection, existing["id"])
                record["idempotent_replay"] = True
                return record
            now = self.clock()
            deployment_id = str(uuid.uuid4())
            state = AWAITING_APPROVAL
            try:
                connection.execute(
                    "INSERT INTO deployments(id, project_id, environment, actor_id, commit_sha,"
                    " artifact_digest, idempotency_key, request_fingerprint, state, checks_sha,"
                    " policy_revision, authorization_generation, approved_by, approved_at, external_id,"
                    " previous_digest, previous_deployment_id, lease_id, lease_fence,"
                    " environment_generation, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, NULL, NULL, NULL,"
                    " NULL, NULL, 0, ?, ?)",
                    (deployment_id, project_id, environment, actor_id, commit_sha, artifact_digest,
                     idempotency_key, fingerprint, state, self.policy_revision,
                     self.store.authorization_grant(connection, actor_id, project_id), now, now))
            except sqlite3.IntegrityError:
                raise DomainError(409, "idempotency_conflict",
                                  "This idempotency key already names a deployment.") from None
            self.store._event(connection, actor_id, project_id, "deploy.queued", {
                "deployment_id": deployment_id, "environment": environment, "commit_sha": commit_sha,
                "artifact_digest": artifact_digest, "idempotency_key": idempotency_key, "state": state,
                "policy_revision": self.policy_revision,
            })
            return self._load(connection, deployment_id)

    def approve(self, actor_id: str, deployment_id: str) -> dict:
        with self.store._connection(write=True) as connection:
            deployment = _row(connection, deployment_id)
            project_id = deployment["project_id"]
            self.store._authorize(connection, actor_id, project_id, write=True, owner=True)
            if _bound_fingerprint(deployment) != deployment["request_fingerprint"]:
                raise DomainError(409, "approval_binding_changed",
                                  "The immutable set moved after the request; enqueue it again.")
            if deployment["state"] != AWAITING_APPROVAL:
                raise DomainError(409, "deployment_not_approvable",
                                  f"This deployment is {deployment['state']}; "
                                  "only a request awaiting approval can be approved.")
            fingerprint = deployment["request_fingerprint"]
            now = self.clock()
            connection.execute(
                "INSERT INTO deployment_approvals(deployment_id, project_id, environment, commit_sha,"
                " artifact_digest, policy_revision, approver_id, fingerprint, approved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (deployment_id, project_id, deployment["environment"], deployment["commit_sha"],
                 deployment["artifact_digest"], deployment["policy_revision"], actor_id, fingerprint, now))
            connection.execute(
                "UPDATE deployments SET state = ?, updated_at = ? WHERE id = ?",
                (QUEUED, now, deployment_id))
            self.store._event(connection, actor_id, project_id, "deploy.approved", {
                "deployment_id": deployment_id, "environment": deployment["environment"],
                "commit_sha": deployment["commit_sha"], "artifact_digest": deployment["artifact_digest"],
                "policy_revision": deployment["policy_revision"], "fingerprint": fingerprint,
            })
            return self._load(connection, deployment_id)

    def record_checks(self, actor_id: str, deployment_id: str, checks_sha: str,
                      artifact_digest: str) -> dict:
        checks_sha = _sha(checks_sha, "checks_sha")
        artifact_digest = _digest(artifact_digest, "artifact_digest")
        with self.store._connection(write=True) as connection:
            deployment = _row(connection, deployment_id)
            self.store._authorize(connection, actor_id, deployment["project_id"], write=True)
            if deployment["state"] not in (QUEUED, AWAITING_APPROVAL):
                raise DomainError(409, "deployment_not_recordable",
                                  f"This deployment is {deployment['state']}; its artefact is already fixed.")
            connection.execute(
                "UPDATE deployments SET checks_sha = ?, artifact_digest = ?, updated_at = ? WHERE id = ?",
                (checks_sha, artifact_digest, self.clock(), deployment_id))
            self.store._event(connection, actor_id, deployment["project_id"], "deploy.checked", {
                "deployment_id": deployment_id, "checks_sha": checks_sha,
                "artifact_digest": artifact_digest,
            })
            return self._load(connection, deployment_id)

    def get(self, user_id: str, project_id: str, deployment_id: str) -> dict:
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            return self._load(connection, deployment_id)

    def list(self, user_id: str, project_id: str) -> list[dict]:
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            return [self._load(connection, row["id"]) for row in connection.execute(
                "SELECT id FROM deployments WHERE project_id = ? ORDER BY created_at, id", (project_id,))]

    @staticmethod
    def _load(connection, deployment_id: str) -> dict:
        row = connection.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
        approval = connection.execute(
            "SELECT approver_id, approved_at FROM deployment_approvals WHERE deployment_id = ?",
            (deployment_id,)).fetchone()
        return {
            "id": row["id"], "project_id": row["project_id"], "environment": row["environment"],
            "actor_id": row["actor_id"], "commit_sha": row["commit_sha"],
            "artifact_digest": row["artifact_digest"], "idempotency_key": row["idempotency_key"],
            "state": row["state"], "checks_sha": row["checks_sha"],
            "policy_revision": row["policy_revision"],
            "authorization_generation": row["authorization_generation"],
            "approved_by": approval["approver_id"] if approval else None,
            "approved_at": approval["approved_at"] if approval else None,
            "external_id": row["external_id"], "previous_digest": row["previous_digest"],
            "previous_deployment_id": row["previous_deployment_id"], "lease_id": row["lease_id"],
            "lease_fence": row["lease_fence"], "environment_generation": row["environment_generation"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "idempotent_replay": False,
        }


class DeployWorker:
    def __init__(self, store: Store, destination: Destination, agent_id: str = "deploy-worker",
                 lease_ttl: int = 120, clock: Callable[[], float] = time.time):
        self.store = store
        self.destination = destination
        self.agent_id = agent_id
        self.lease_ttl = lease_ttl
        self.clock = clock

    def run_next(self, project_id: str, environment: str) -> dict:
        environment = _environment(environment)
        with self.store._connection() as connection:
            if not connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                raise DomainError(404, "project_not_found", "Project does not exist.")
            if connection.execute(
                    "SELECT 1 FROM deployments WHERE project_id = ? AND environment = ? AND state = ?",
                    (project_id, environment, UNKNOWN)).fetchone():
                raise DomainError(409, "environment_unknown",
                                  f"{environment} holds an undecided deployment; promotions stop until it is resolved.")
            pending = connection.execute(
                "SELECT id, state FROM deployments WHERE project_id = ? AND environment = ?"
                " AND state IN (?, ?) ORDER BY created_at, id LIMIT 1",
                (project_id, environment, RECONCILING, QUEUED)).fetchone()
        if pending is None:
            return {"id": None, "project_id": project_id, "environment": environment, "state": "idle",
                    "detail": "No approved deployment waits for this environment."}
        if pending["state"] == RECONCILING:
            return self._reconcile(pending["id"])
        return self._start(pending["id"])

    def rollback(self, deployment_id: str, previous_digest: str, expected_active_deployment_id: str,
                 expected_digest: str, environment_generation: int) -> dict:
        previous_digest = _digest(previous_digest, "previous_digest")
        if type(environment_generation) is not int or environment_generation < 0:
            raise DomainError(400, "invalid_generation", "environment_generation must be a nonnegative integer.")
        with self.store._connection(write=True) as connection:
            deployment = _row(connection, deployment_id)
            project_id, environment = deployment["project_id"], deployment["environment"]
            self._authorize_effect(connection, deployment)
            if deployment["state"] != HEALTHY:
                raise DomainError(409, "deployment_not_healthy",
                                  f"This deployment is {deployment['state']}; only a healthy one rolls back.")
            current = _environment_row(connection, project_id, environment)
            if (current is None
                    or current["active_deployment_id"] != expected_active_deployment_id
                    or current["active_digest"] != expected_digest
                    or int(current["generation"]) != environment_generation):
                raise DomainError(409, "stale_rollback",
                                  "The environment moved since these expectations were taken; nothing changed.")
            if deployment["previous_digest"] != previous_digest:
                raise DomainError(409, "previous_digest_unknown",
                                  "The previous digest of this deployment is not the one requested.")
            lease = self._reserve(connection, deployment)
            self.store._event(connection, deployment["actor_id"], project_id, "deploy.rollback.requested", {
                "deployment_id": deployment_id, "environment": environment,
                "previous_digest": previous_digest,
                "expected_active_deployment_id": expected_active_deployment_id,
                "expected_digest": expected_digest, "environment_generation": environment_generation,
                "fence": lease["fence"],
            })
        change = self._change(deployment, previous_digest, lease)
        try:
            result = self.destination.promote(change)
        except DestinationTimeout as timeout:
            with self.store._connection(write=True) as connection:
                self._finish(connection, deployment_id, RECONCILING, lease,
                             external_id=timeout.external_id,
                             detail="The destination timed out during the rollback.")
                return self._load(connection, deployment_id)
        report = self.destination.health(previous_digest)
        healthy = bool(report.get("healthy"))
        with self.store._connection(write=True) as connection:
            self._finish(connection, deployment_id, ROLLED_BACK if healthy else FAILED, lease,
                         external_id=result["external_id"], detail=report.get("detail", ""))
            if healthy:
                self._activate(connection, project_id, environment,
                               deployment["previous_deployment_id"], previous_digest)
            return self._load(connection, deployment_id)

    def _start(self, deployment_id: str) -> dict:
        with self.store._connection(write=True) as connection:
            deployment = _row(connection, deployment_id)
            if deployment["state"] != QUEUED:
                raise DomainError(409, "deployment_not_queued",
                                  f"This deployment is {deployment['state']}; only an approved one starts.")
            self._authorize_effect(connection, deployment)
            lease = self._reserve(connection, deployment)
            record = self._load(connection, deployment_id)
        change = self._change(record, record["artifact_digest"], lease)
        try:
            result = self.destination.promote(change)
        except DestinationTimeout as timeout:
            with self.store._connection(write=True) as connection:
                self._finish(connection, deployment_id, RECONCILING, lease,
                             external_id=timeout.external_id,
                             detail="The destination timed out; its state is read before any re-run.")
                return self._load(connection, deployment_id)
        report = self.destination.health(record["artifact_digest"])
        healthy = bool(report.get("healthy"))
        with self.store._connection(write=True) as connection:
            self._finish(connection, deployment_id, HEALTHY if healthy else FAILED, lease,
                         external_id=result["external_id"], detail=report.get("detail", ""))
            if healthy:
                self._activate(connection, record["project_id"], record["environment"],
                               deployment_id, record["artifact_digest"])
            settled = self._load(connection, deployment_id)
        if not healthy:
            self._restore(settled)
        return settled

    def _reconcile(self, deployment_id: str) -> dict:
        with self.store._connection() as connection:
            deployment = _row(connection, deployment_id)
        answer = self.destination.describe(deployment["external_id"])
        if not answer.get("decided"):
            with self.store._connection(write=True) as connection:
                self._settle_unknown(connection, deployment_id)
                return self._load(connection, deployment_id)
        if answer.get("digest") != deployment["artifact_digest"]:
            with self.store._connection(write=True) as connection:
                self._settle_refused(connection, deployment_id, deployment["external_id"],
                                      "The destination serves another artefact than the one requested.")
                return self._load(connection, deployment_id)
        report = self.destination.health(deployment["artifact_digest"])
        with self.store._connection(write=True) as connection:
            if report.get("healthy"):
                self._activate(connection, deployment["project_id"], deployment["environment"],
                               deployment_id, deployment["artifact_digest"])
                self._settle_state(connection, deployment_id, HEALTHY,
                                   detail=report.get("detail", ""))
            else:
                self._settle_refused(connection, deployment_id, deployment["external_id"],
                                      report.get("detail", "The health check failed after reconciliation."))
            return self._load(connection, deployment_id)

    def _restore(self, settled: dict) -> None:
        previous_digest = settled["previous_digest"]
        if not previous_digest:
            return
        deployment_id = settled["id"]
        with self.store._connection(write=True) as connection:
            deployment = _row(connection, deployment_id)
            lease = self._reserve(connection, deployment)
            self.store._event(connection, deployment["actor_id"], deployment["project_id"],
                              "deploy.restoring", {
                                  "deployment_id": deployment_id, "environment": deployment["environment"],
                                  "previous_digest": previous_digest, "fence": lease["fence"],
                              })
        change = self._change(settled, previous_digest, lease)
        try:
            self.destination.promote(change)
            report = self.destination.health(previous_digest)
        except DomainError as error:
            report = {"healthy": False, "detail": str(error)}
        with self.store._connection(write=True) as connection:
            self._release(connection, deployment_id, lease)
            self.store._event(connection, deployment["actor_id"], deployment["project_id"],
                              "deploy.restored" if report.get("healthy") else "deploy.restore_failed", {
                                  "deployment_id": deployment_id,
                                  "environment": deployment["environment"],
                                  "previous_digest": previous_digest, "fence": lease["fence"],
                              })

    def _change(self, deployment: dict, digest: str, lease: dict) -> ArtifactChange:
        return ArtifactChange(deployment["project_id"], deployment["environment"], digest,
                              deployment["id"], lease["fence"], deployment["idempotency_key"],
                              lambda: self._permit(deployment["id"], lease))

    def _permit(self, deployment_id: str, lease: dict) -> dict:
        with self.store._connection() as connection:
            deployment = _row(connection, deployment_id)
            if deployment["state"] != RUNNING:
                raise DomainError(409, "deployment_not_running",
                                  f"This deployment is {deployment['state']}; it no longer holds the environment.")
            self._authorize_effect(connection, deployment)
            return self.store._held_lease(connection, deployment["actor_id"], deployment["project_id"],
                                          lease["id"], lease["fence"])

    def _authorize_effect(self, connection, deployment) -> None:
        project_id = deployment["project_id"]
        actor_id = deployment["actor_id"]
        self.store._authorize(connection, actor_id, project_id, write=True, owner=True)
        generation = self.store.authorization_grant(connection, actor_id, project_id)
        if generation != deployment["authorization_generation"]:
            raise DomainError(409, "generation_stale",
                              f"Authorization generation is {generation}; this request must be enqueued again.")
        if deployment["checks_sha"] is None:
            raise DomainError(409, "checks_missing", "The checks of this artefact were never recorded.")
        if deployment["checks_sha"] != deployment["commit_sha"]:
            raise DomainError(409, "checks_sha_mismatch",
                              "The recorded checks belong to another commit than the one requested.")
        if _bound_fingerprint(deployment) != deployment["request_fingerprint"]:
            raise DomainError(409, "approval_binding_changed",
                              "The immutable set moved after the request; enqueue it again.")
        approval = connection.execute(
            "SELECT * FROM deployment_approvals WHERE deployment_id = ?", (deployment["id"],)).fetchone()
        if approval is None:
            raise DomainError(409, "approval_missing",
                              "This deployment has no approval bound to its immutable set.")
        if approval["fingerprint"] != deployment["request_fingerprint"]:
            raise DomainError(409, "approval_binding_changed",
                              "The approval does not match the immutable set of this deployment.")
        if approval["artifact_digest"] != deployment["artifact_digest"]:
            raise DomainError(409, "approval_digest_changed",
                              "The approved digest is not the digest this deployment carries.")

    def _reserve(self, connection, deployment) -> dict:
        acquired = self.store._acquire(connection, deployment["actor_id"], deployment["project_id"],
                                       self.agent_id, ["deploy:" + deployment["environment"]],
                                       self.lease_ttl, "owner")
        current = _environment_row(connection, deployment["project_id"], deployment["environment"])
        now = self.clock()
        connection.execute(
            "UPDATE deployments SET state = ?, lease_id = ?, lease_fence = ?, previous_digest = ?,"
            " previous_deployment_id = ?, environment_generation = ?, updated_at = ? WHERE id = ?",
            (RUNNING, acquired[0]["id"], acquired[0]["fence"],
             current["active_digest"] if current is not None else None,
             current["active_deployment_id"] if current is not None else None,
             int(current["generation"]) if current is not None else 0, now, deployment["id"]))
        self.store._event(connection, deployment["actor_id"], deployment["project_id"], "deploy.running", {
            "deployment_id": deployment["id"], "environment": deployment["environment"],
            "artifact_digest": deployment["artifact_digest"], "checks_sha": deployment["checks_sha"],
            "fence": acquired[0]["fence"],
            "previous_digest": current["active_digest"] if current is not None else None,
        })
        return acquired[0]

    def _activate(self, connection, project_id: str, environment: str, deployment_id, digest: str) -> None:
        connection.execute(
            "INSERT INTO deployment_environments(project_id, environment, active_deployment_id,"
            " active_digest, generation, updated_at) VALUES (?, ?, ?, ?, 1, ?)"
            " ON CONFLICT(project_id, environment) DO UPDATE SET"
            " active_deployment_id = excluded.active_deployment_id,"
            " active_digest = excluded.active_digest,"
            " generation = deployment_environments.generation + 1,"
            " updated_at = excluded.updated_at",
            (project_id, environment, deployment_id, digest, self.clock()))

    def _finish(self, connection, deployment_id: str, state: str, lease: dict,
                external_id: str | None = None, detail: str = "") -> None:
        self._release(connection, deployment_id, lease)
        connection.execute(
            "UPDATE deployments SET state = ?, external_id = COALESCE(?, external_id), updated_at = ?"
            " WHERE id = ?", (state, external_id, self.clock(), deployment_id))
        self._event(connection, deployment_id, state, detail)

    def _settle_unknown(self, connection, deployment_id: str) -> None:
        connection.execute("UPDATE deployments SET state = ?, updated_at = ? WHERE id = ?",
                           (UNKNOWN, self.clock(), deployment_id))
        self._event(connection, deployment_id, UNKNOWN,
                    "The destination cannot decide whether the change landed.")

    def _settle_refused(self, connection, deployment_id: str, external_id: str | None, detail: str) -> None:
        connection.execute(
            "UPDATE deployments SET state = ?, external_id = COALESCE(?, external_id), updated_at = ?"
            " WHERE id = ?", (FAILED, external_id, self.clock(), deployment_id))
        self._event(connection, deployment_id, FAILED, detail)

    def _settle_state(self, connection, deployment_id: str, state: str, detail: str) -> None:
        connection.execute("UPDATE deployments SET state = ?, updated_at = ? WHERE id = ?",
                           (state, self.clock(), deployment_id))
        self._event(connection, deployment_id, state, detail)

    def _release(self, connection, deployment_id: str, lease: dict) -> None:
        connection.execute("DELETE FROM leases WHERE id = ?", (lease["id"],))
        connection.execute("UPDATE deployments SET lease_id = NULL, lease_fence = NULL WHERE id = ?",
                           (deployment_id,))
        self._event(connection, deployment_id, "lease_released",
                    f"Fence {lease['fence']} released.", kind="deploy.lease_released")

    def _event(self, connection, deployment_id: str, state: str, detail: str,
               kind: str | None = None) -> None:
        row = connection.execute(
            "SELECT project_id, actor_id, environment FROM deployments WHERE id = ?",
            (deployment_id,)).fetchone()
        connection.execute(
            "INSERT INTO events(project_id, user_id, kind, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (row["project_id"], row["actor_id"], kind or _EVENT_KINDS[state],
             json.dumps({"deployment_id": deployment_id, "environment": row["environment"],
                         "detail": detail}, separators=(",", ":"), sort_keys=True),
             self.clock()))


def _row(connection, deployment_id: str):
    if not isinstance(deployment_id, str) or not deployment_id.strip():
        raise DomainError(400, "invalid_deployment", "deployment_id must be a nonempty string.")
    row = connection.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
    if row is None:
        raise DomainError(404, "deployment_not_found", "That deployment does not exist.")
    return row


DeployWorker._load = staticmethod(DeployService._load)


def _environment_row(connection, project_id: str, environment: str):
    return connection.execute(
        "SELECT * FROM deployment_environments WHERE project_id = ? AND environment = ?",
        (project_id, environment)).fetchone()


def _environment(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(400, "invalid_environment", "environment must be a nonempty string.")
    try:
        canonical = _resource("deploy:" + value.strip())
    except DomainError:
        raise DomainError(400, "invalid_environment",
                          "environment must use 1..64 letters, numbers, underscores or hyphens.") from None
    return canonical[len("deploy:"):]


def _sha(value: str, field: str) -> str:
    text = _text(value, field, 64)
    if not _SHA_PATTERN.fullmatch(text):
        raise DomainError(400, "invalid_sha", f"{field} must be a lowercase 40 character SHA.")
    return text


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value.strip()):
        raise DomainError(400, "invalid_digest", f"{field} must be sha256: followed by 64 lowercase hex characters.")
    return value.strip()


def _fingerprint(project_id: str, environment: str, commit_sha: str, artifact_digest: str,
                 policy_revision: str) -> str:
    payload = json.dumps({"project_id": project_id, "environment": environment, "commit_sha": commit_sha,
                          "artifact_digest": artifact_digest, "policy_revision": policy_revision},
                         separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bound_fingerprint(deployment) -> str:
    return _fingerprint(deployment["project_id"], deployment["environment"], deployment["commit_sha"],
                        deployment["artifact_digest"], deployment["policy_revision"])