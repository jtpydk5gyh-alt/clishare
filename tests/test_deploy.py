import tempfile
import threading
import unittest
from pathlib import Path

from cshcli.deploy import (
    AWAITING_APPROVAL, DeployService, DeployWorker, FAILED, HEALTHY, InProcessDestination,
    QUEUED, RECONCILING, ROLLED_BACK, STATES, UNKNOWN,
)
from cshcli.errors import DomainError
from cshcli.store import Store


SHA = "a" * 40
SHA_B = "b" * 40
DIGEST = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64
DIGEST_C = "sha256:" + "3" * 64


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.ana = self.store.register_user("ana")
        self.luis = self.store.register_user("luis")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.destination = InProcessDestination()
        self.service = DeployService(self.store)
        self.worker = DeployWorker(self.store, self.destination)
        self.owner = self.ana["id"]

    def enqueue(self, digest=DIGEST, sha=SHA, key="release-1", environment="staging", user=None):
        return self.service.enqueue(user or self.owner, self.project["id"], environment,
                                    sha, digest, key)

    def approved(self, digest=DIGEST, sha=SHA, key="release-1", environment="staging", user=None):
        deployment = self.enqueue(digest, sha, key, environment, user)
        self.service.record_checks(self.owner, deployment["id"], sha, digest)
        return self.service.approve(self.owner, deployment["id"])

    def add_member(self, role="member"):
        invite = self.store.create_invite(self.owner, self.project["id"], role)
        joined = self.store.accept_invite(self.luis["id"], invite["token"])
        return self.luis["id"], role

    def state(self, deployment_id):
        with self.store._connection() as connection:
            return connection.execute("SELECT state FROM deployments WHERE id = ?",
                                      (deployment_id,)).fetchone()["state"]

    def environment_row(self):
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM deployment_environments WHERE project_id = ? AND environment = ?",
                (self.project["id"], "staging")).fetchone()
            return dict(row) if row is not None else None

    def active_digest(self):
        row = self.environment_row()
        return row["active_digest"] if row is not None else None

    def event_kinds(self):
        return [event["kind"] for event in self.store.list_events(self.owner, self.project["id"])]

    def test_every_state_the_plan_names_is_persisted(self):
        self.assertEqual(set(STATES), {"queued", "awaiting_approval", "running", "reconciling",
                                       "unknown", "healthy", "failed", "rolled_back"})

    def test_a_request_waits_for_an_approval(self):
        deployment = self.enqueue()
        self.assertEqual(deployment["state"], AWAITING_APPROVAL)
        self.assertIsNone(deployment["approved_by"])
        self.assertEqual(self.worker.run_next(self.project["id"], "staging")["state"], "idle")
        self.assertEqual(self.destination.promotions, [])

    def test_the_same_key_with_the_same_payload_returns_the_same_deployment(self):
        first = self.enqueue()
        second = self.enqueue()
        self.assertEqual(second["id"], first["id"])
        self.assertTrue(second["idempotent_replay"])
        with self.store._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM deployments").fetchone()[0]
        self.assertEqual(count, 1)

    def test_the_same_key_with_a_different_payload_is_refused(self):
        self.enqueue()
        with self.assertRaises(DomainError) as caught:
            self.enqueue(digest=DIGEST_B)
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        self.assertEqual(caught.exception.status, 409)

    def test_the_idempotency_key_is_scoped_per_project_and_environment(self):
        first = self.enqueue(environment="staging")
        production = self.enqueue(environment="production")
        other = self.store.create_project(self.luis["id"], "otro")
        foreign = self.service.enqueue(self.luis["id"], other["id"], "staging", SHA, DIGEST, "release-1")
        self.assertEqual(len({first["id"], production["id"], foreign["id"]}), 3)

    def test_approval_binds_the_immutable_set(self):
        deployment = self.approved()
        self.assertEqual(deployment["state"], QUEUED)
        self.assertEqual(deployment["approved_by"], self.owner)
        with self.store._connection() as connection:
            approval = connection.execute(
                "SELECT * FROM deployment_approvals WHERE deployment_id = ?",
                (deployment["id"],)).fetchone()
        self.assertEqual(approval["commit_sha"], SHA)
        self.assertEqual(approval["artifact_digest"], DIGEST)
        self.assertEqual(approval["policy_revision"], deployment["policy_revision"])
        self.assertEqual(approval["environment"], "staging")
        self.assertEqual(approval["project_id"], self.project["id"])

    def test_approving_after_the_digest_changed_is_refused(self):
        deployment = self.enqueue()
        self.service.record_checks(self.owner, deployment["id"], SHA, DIGEST_B)
        with self.assertRaises(DomainError) as caught:
            self.service.approve(self.owner, deployment["id"])
        self.assertEqual(caught.exception.code, "approval_binding_changed")
        self.assertEqual(caught.exception.status, 409)

    def test_approving_without_the_owner_role_is_refused(self):
        deployment = self.enqueue()
        member, _ = self.add_member("member")
        with self.assertRaises(DomainError) as caught:
            self.service.approve(member, deployment["id"])
        self.assertEqual(caught.exception.code, "forbidden")

    def test_a_non_member_cannot_approve(self):
        deployment = self.enqueue()
        with self.assertRaises(DomainError) as caught:
            self.service.approve(self.luis["id"], deployment["id"])
        self.assertEqual(caught.exception.code, "forbidden")

    def test_a_healthy_deployment_records_what_the_environment_serves(self):
        deployment = self.approved()
        settled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(settled["state"], HEALTHY)
        self.assertEqual(self.destination.active["staging"], DIGEST)
        self.assertIsNotNone(settled["external_id"])
        row = self.environment_row()
        self.assertEqual(row["active_deployment_id"], deployment["id"])
        self.assertEqual(row["active_digest"], DIGEST)
        self.assertEqual(row["generation"], 1)
        self.assertIn("deploy.healthy", self.event_kinds())

    def test_the_worker_refuses_without_recorded_checks(self):
        deployment = self.enqueue()
        self.service.approve(self.owner, deployment["id"])
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(caught.exception.code, "checks_missing")
        self.assertEqual(self.destination.promotions, [])

    def test_checks_of_another_commit_are_refused(self):
        deployment = self.enqueue()
        self.service.record_checks(self.owner, deployment["id"], SHA_B, DIGEST)
        self.service.approve(self.owner, deployment["id"])
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(caught.exception.code, "checks_sha_mismatch")

    def test_a_revocation_after_approval_stops_the_deployment(self):
        deployment = self.approved()
        self.store.revoke_authorization(self.owner, self.project["id"], self.owner)
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(caught.exception.code, "generation_stale")
        self.assertEqual(self.destination.promotions, [])
        self.assertEqual(self.state(deployment["id"]), QUEUED)

    def test_a_revocation_between_the_check_and_the_effect_stops_the_change(self):
        self.approved()
        store, project_id, owner_id = self.store, self.project["id"], self.owner

        class RevokingDestination(InProcessDestination):
            def promote(self, change):
                store.revoke_authorization(owner_id, project_id, owner_id)
                return InProcessDestination.promote(self, change)

        self.worker.destination = RevokingDestination()
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(caught.exception.code, "generation_stale")
        self.assertEqual(self.destination.promotions, [])

    def test_the_environment_lease_is_taken_and_released(self):
        deployment = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(self.store.list_leases(self.owner, self.project["id"]), [])
        self.assertIn("deploy.lease_released", self.event_kinds())
        self.assertIsNone(self.service.get(self.owner, self.project["id"],
                                           deployment["id"])["lease_fence"])

    def test_a_stale_fence_is_refused_by_the_destination(self):
        self.approved(key="release-1")
        self.worker.run_next(self.project["id"], "staging")
        with self.store._connection(write=True) as connection:
            lease = self.store._acquire(connection, self.owner, self.project["id"], "deploy-worker",
                                        ["deploy:staging"], 120, "owner")[0]
        from cshcli.deploy import ArtifactChange
        stale = ArtifactChange(self.project["id"], "staging", DIGEST_B, "other", lease["fence"] - 1,
                               "release-9", lambda: {})
        with self.assertRaises(DomainError) as caught:
            self.destination.promote(stale)
        self.assertEqual(caught.exception.code, "stale_fence")
        self.assertEqual(self.destination.active["staging"], DIGEST)

    def test_eleven_workers_racing_one_environment_change_it_once(self):
        self.approved()
        outcomes = []
        barrier = threading.Barrier(11)

        def attempt():
            worker = DeployWorker(self.store, self.destination, agent_id=f"worker-{threading.get_ident()}")
            barrier.wait()
            try:
                outcomes.append(worker.run_next(self.project["id"], "staging"))
            except DomainError:
                outcomes.append(None)

        threads = [threading.Thread(target=attempt) for _ in range(11)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [item for item in outcomes if item is not None and item["state"] == HEALTHY]
        self.assertEqual(len(winners), 1, "exactly one worker may change the environment")
        self.assertEqual(len(self.destination.promotions), 1)
        self.assertEqual(self.destination.active["staging"], DIGEST)

    def test_an_ambiguous_timeout_reconciles_instead_of_retrying(self):
        deployment = self.approved()
        self.destination.timing_out_digests.add(DIGEST)
        timed_out = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(timed_out["state"], RECONCILING)
        self.assertIsNotNone(timed_out["external_id"])
        self.assertEqual(len(self.destination.promotions), 1)
        reconciled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(reconciled["state"], HEALTHY)
        self.assertEqual(len(self.destination.promotions), 1, "a re-run must not touch the destination again")
        self.assertEqual(reconciled["external_id"], timed_out["external_id"])
        self.assertEqual(self.environment_row()["active_digest"], DIGEST)

    def test_a_reconciliation_that_finds_another_artefact_fails(self):
        deployment = self.approved()
        self.destination.timing_out_digests.add(DIGEST)
        self.worker.run_next(self.project["id"], "staging")
        self.destination.external[self.destination.promotions[0]["external_id"]] = DIGEST_C
        settled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(settled["state"], FAILED)
        self.assertEqual(self.active_digest(), None)

    def test_a_destination_that_cannot_decide_stays_unknown_and_stops_promotions(self):
        self.approved()
        self.destination.timing_out_digests.add(DIGEST)
        timed_out = self.worker.run_next(self.project["id"], "staging")
        self.destination.undecidable.add(timed_out["external_id"])
        settled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(settled["state"], UNKNOWN)
        self.service.enqueue(self.owner, self.project["id"], "staging", SHA_B, DIGEST_B, "release-2")
        second = self.service.get(self.owner, self.project["id"],
                                  self.service.list(self.owner, self.project["id"])[1]["id"])
        self.service.record_checks(self.owner, second["id"], SHA_B, DIGEST_B)
        self.service.approve(self.owner, second["id"])
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(caught.exception.code, "environment_unknown")
        self.assertEqual(len(self.destination.promotions), 1)

    def test_a_failed_health_check_never_becomes_healthy(self):
        deployment = self.approved()
        self.destination.failing_digests.add(DIGEST)
        settled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(settled["state"], FAILED)
        self.assertNotEqual(settled["state"], HEALTHY)
        self.assertIsNone(self.active_digest())
        self.assertIn("deploy.failed", self.event_kinds())

    def test_a_failed_health_check_restores_the_previous_digest(self):
        self.approved(digest=DIGEST, key="release-1")
        self.worker.run_next(self.project["id"], "staging")
        self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.destination.failing_digests.add(DIGEST_B)
        settled = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(settled["state"], FAILED)
        self.assertEqual(self.destination.active["staging"], DIGEST)
        self.assertIn("deploy.restored", self.event_kinds())

    def test_a_late_rollback_does_not_undo_a_newer_healthy_deployment(self):
        first = self.approved(digest=DIGEST, key="release-1")
        self.worker.run_next(self.project["id"], "staging")
        before = self.environment_row()
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(self.environment_row()["active_digest"], DIGEST_B)
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(first["id"], DIGEST_C, before["active_deployment_id"],
                                 before["active_digest"], before["generation"])
        self.assertEqual(caught.exception.code, "stale_rollback")
        self.assertEqual(self.environment_row()["active_digest"], DIGEST_B)
        self.assertEqual(self.state(second["id"]), HEALTHY)
        self.assertEqual(self.destination.active["staging"], DIGEST_B)

    def test_a_rollback_moves_the_environment_back_to_the_previous_digest(self):
        first = self.approved(digest=DIGEST, key="release-1")
        self.worker.run_next(self.project["id"], "staging")
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        current = self.environment_row()
        settled = self.worker.rollback(second["id"], DIGEST, current["active_deployment_id"],
                                       current["active_digest"], current["generation"])
        self.assertEqual(settled["state"], ROLLED_BACK)
        self.assertEqual(self.destination.active["staging"], DIGEST)
        row = self.environment_row()
        self.assertEqual(row["active_digest"], DIGEST)
        self.assertEqual(row["active_deployment_id"], first["id"])
        self.assertEqual(row["generation"], current["generation"] + 1)
        self.assertIn("deploy.rollback.requested", self.event_kinds())

    def test_a_rollback_with_a_stale_generation_leaves_the_state_alone(self):
        self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        current = self.environment_row()
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(second["id"], DIGEST, current["active_deployment_id"],
                                 current["active_digest"], current["generation"] - 1)
        self.assertEqual(caught.exception.code, "stale_rollback")
        self.assertEqual(self.state(second["id"]), HEALTHY)
        self.assertEqual(self.environment_row()["active_digest"], DIGEST_B)

    def test_a_rollback_with_a_wrong_expected_digest_is_refused(self):
        self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        current = self.environment_row()
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(second["id"], DIGEST, current["active_deployment_id"], DIGEST,
                                 current["generation"])
        self.assertEqual(caught.exception.code, "stale_rollback")
        self.assertEqual(self.destination.active["staging"], DIGEST_B)

    def test_a_rollback_reserves_the_environment_lease_and_leaves_an_audit_event(self):
        self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        current = self.environment_row()
        events_before = len(self.store.list_events(self.owner, self.project["id"], limit=1000))
        self.worker.rollback(second["id"], DIGEST, current["active_deployment_id"],
                             current["active_digest"], current["generation"])
        kinds = self.event_kinds()
        self.assertIn("deploy.rollback.requested", kinds)
        self.assertIn("deploy.lease_released", kinds)
        self.assertGreater(len(self.store.list_events(self.owner, self.project["id"], limit=1000)),
                           events_before)
        self.assertEqual(self.store.list_leases(self.owner, self.project["id"]), [])

    def test_a_rollback_of_an_unhealthy_deployment_is_refused(self):
        deployment = self.approved()
        self.destination.failing_digests.add(DIGEST)
        self.worker.run_next(self.project["id"], "staging")
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(deployment["id"], DIGEST_B, deployment["id"], DIGEST, 0)
        self.assertEqual(caught.exception.code, "deployment_not_healthy")

    def test_a_rollback_that_names_another_previous_digest_is_refused(self):
        self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        self.worker.run_next(self.project["id"], "staging")
        current = self.environment_row()
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(second["id"], DIGEST_C, current["active_deployment_id"],
                                 current["active_digest"], current["generation"])
        self.assertEqual(caught.exception.code, "previous_digest_unknown")

    def test_the_digest_must_be_explicit_and_never_read_from_head(self):
        for digest in ("HEAD", "main", "", "sha256:" + "z" * 64, "1" * 64, None, 42):
            with self.subTest(digest=digest):
                with self.assertRaises(DomainError):
                    self.enqueue(digest=digest)

    def test_the_commit_sha_must_be_a_sha(self):
        for sha in ("main", "abc", "z" * 40, "", None):
            with self.subTest(sha=sha):
                with self.assertRaises(DomainError):
                    self.enqueue(sha=sha)

    def test_the_environment_must_be_a_plain_name(self):
        for environment in ("", "../prod", "a/b", None, "x" * 65):
            with self.subTest(environment=environment):
                with self.assertRaises(DomainError):
                    self.enqueue(environment=environment)

    def test_every_environment_awaits_an_owner_approval(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                deployment = self.service.enqueue(self.owner, self.project["id"], environment,
                                                  SHA, DIGEST, "key-" + environment)
                self.assertEqual(deployment["state"], AWAITING_APPROVAL)

    def test_a_non_member_cannot_enqueue(self):
        with self.assertRaises(DomainError) as caught:
            self.enqueue(user=self.luis["id"])
        self.assertEqual(caught.exception.code, "forbidden")

    def test_an_environment_that_does_not_exist_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.worker.run_next("no-project", "staging")
        self.assertEqual(caught.exception.code, "project_not_found")

    def test_an_unknown_deployment_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback("no-deployment", DIGEST, "x", DIGEST, 0)
        self.assertEqual(caught.exception.code, "deployment_not_found")

    def test_an_idle_environment_reports_no_work(self):
        result = self.worker.run_next(self.project["id"], "staging")
        self.assertIsNone(result["id"])
        self.assertEqual(result["state"], "idle")

    def test_checks_cannot_be_recorded_after_the_artefact_moved(self):
        deployment = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        with self.assertRaises(DomainError) as caught:
            self.service.record_checks(self.owner, deployment["id"], SHA_B, DIGEST_B)
        self.assertEqual(caught.exception.code, "deployment_not_recordable")

    def test_the_worker_exposes_no_credential_or_head_lookup(self):
        for name in ("head", "checkout", "git", "token", "credential", "read_head"):
            self.assertFalse(hasattr(self.worker, name), f"DeployWorker must not expose {name}.")


if __name__ == "__main__":
    unittest.main()