import tempfile
import unittest
from pathlib import Path

from cshcli.deploy import DeployService, DeployWorker
from cshcli.errors import DomainError
from cshcli.process_destination import ProcessDestination
from cshcli.store import Store


SHA = "a" * 40
SHA_B = "b" * 40
DIGEST = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64


class ProcessDestinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "coordinator.sqlite3")
        self.ana = self.store.register_user("ana")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.destination = ProcessDestination(self.root / "environment").start()
        self.addCleanup(self.destination.close)
        self.service = DeployService(self.store)
        self.worker = DeployWorker(self.store, self.destination)
        self.owner = self.ana["id"]

    def approved(self, digest=DIGEST, sha=SHA, key="release-1", environment="staging"):
        deployment = self.service.enqueue(self.owner, self.project["id"], environment,
                                          sha, digest, key)
        self.service.record_checks(self.owner, deployment["id"], sha, digest)
        return self.service.approve(self.owner, deployment["id"])

    def record(self, deployment_id):
        return self.service.get(self.owner, self.project["id"], deployment_id)

    def test_a_staging_deploy_against_a_real_process(self):
        deployment = self.approved()
        result = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(result["state"], "healthy")
        self.assertTrue((self.root / "environment" / "active.json").is_file())
        self.assertEqual(self.record(deployment["id"])["state"], "healthy")

    def test_the_destination_survives_a_second_process_reading_it(self):
        deployment = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        import json
        active = json.loads((self.root / "environment" / "active.json").read_text())
        self.assertEqual(active["digest"], DIGEST)
        self.assertEqual(active["external_id"],
                         self.record(deployment["id"])["external_id"])

    def test_an_induced_health_failure_never_becomes_healthy(self):
        deployment = self.approved()
        self.destination.stop_server()
        result = self.worker.run_next(self.project["id"], "staging")
        self.assertEqual(result["state"], "failed")
        self.assertNotEqual(self.record(deployment["id"])["state"], "healthy")

    def test_a_health_failure_restores_the_previous_artefact(self):
        first = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.service.enqueue(self.owner, self.project["id"], "staging",
                                      SHA_B, DIGEST_B, "release-2")
        self.service.record_checks(self.owner, second["id"], SHA_B, DIGEST_B)
        self.service.approve(self.owner, second["id"])
        self.destination.stop_server()
        self.worker.run_next(self.project["id"], "staging")
        active = (self.root / "environment" / "active.json").read_text()
        self.assertIn(DIGEST, active)
        self.assertNotIn(DIGEST_B, active)
        self.assertNotEqual(self.record(first["id"])["state"], "failed")

    def test_a_rollback_against_the_real_process(self):
        first = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        second = self.service.enqueue(self.owner, self.project["id"], "staging",
                                      SHA_B, DIGEST_B, "release-2")
        self.service.record_checks(self.owner, second["id"], SHA_B, DIGEST_B)
        self.service.approve(self.owner, second["id"])
        self.worker.run_next(self.project["id"], "staging")
        self.assertIn(DIGEST_B, (self.root / "environment" / "active.json").read_text())

        with self.store._connection() as connection:
            environment = connection.execute(
                "SELECT active_deployment_id, active_digest, generation FROM deployment_environments"
                " WHERE project_id = ? AND environment = ?",
                (self.project["id"], "staging")).fetchone()
        result = self.worker.rollback(second["id"], DIGEST,
                                      environment["active_deployment_id"],
                                      environment["active_digest"],
                                      environment["generation"])
        self.assertEqual(result["state"], "rolled_back")
        active = (self.root / "environment" / "active.json").read_text()
        self.assertIn(DIGEST, active)
        self.assertNotIn(DIGEST_B, active)
        self.assertEqual(self.record(first["id"])["state"], "healthy")

    def test_a_first_deployment_has_nothing_to_roll_back_to(self):
        deployment = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        with self.store._connection() as connection:
            environment = connection.execute(
                "SELECT active_deployment_id, active_digest, generation FROM deployment_environments"
                " WHERE project_id = ? AND environment = ?",
                (self.project["id"], "staging")).fetchone()
        with self.assertRaises(DomainError) as caught:
            self.worker.rollback(deployment["id"], DIGEST,
                                 environment["active_deployment_id"],
                                 environment["active_digest"],
                                 environment["generation"])
        self.assertEqual(caught.exception.code, "previous_digest_unknown")

    def test_an_idempotent_re_send_changes_nothing_twice(self):
        first = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        again = self.service.enqueue(self.owner, self.project["id"], "staging",
                                     SHA, DIGEST, "release-1")
        self.assertEqual(again["id"], first["id"])
        self.assertTrue(again["idempotent_replay"])
        self.assertEqual(self.worker.run_next(self.project["id"], "staging")["state"], "idle")

    def test_a_real_timeout_goes_to_reconciling_and_not_to_a_retry(self):
        deployment = self.approved()
        self.destination.stall()
        try:
            result = self.worker.run_next(self.project["id"], "staging")
        finally:
            self.destination.unstall()
        self.assertEqual(result["state"], "reconciling")
        self.assertEqual(self.record(deployment["id"])["state"], "reconciling")

    def test_a_genuine_timeout_is_not_presented_as_a_healthy_deployment(self):
        deployment = self.approved()
        self.destination.stall()
        try:
            self.worker.run_next(self.project["id"], "staging")
        finally:
            self.destination.unstall()
        self.assertNotEqual(self.record(deployment["id"])["state"], "healthy")

    def test_a_stale_fence_is_refused_by_the_real_process(self):
        self.approved()
        self.worker.run_next(self.project["id"], "staging")
        stale = self.approved(digest=DIGEST_B, sha=SHA_B, key="release-2")
        state = self.record(stale["id"])

        class Stale:
            environment = state["environment"]
            digest = DIGEST_B
            fence = 0
            deployment_id = stale["id"]
            external_key = "k"

            def authorize(self):
                return None

        with self.assertRaises(DomainError) as caught:
            self.destination.promote(Stale())
        self.assertEqual(caught.exception.code, "stale_fence")

    def test_a_second_environment_is_independent(self):
        deployment = self.approved()
        self.worker.run_next(self.project["id"], "staging")
        other = self.service.enqueue(self.owner, self.project["id"], "production",
                                     SHA_B, DIGEST_B, "prod-1")
        self.service.record_checks(self.owner, other["id"], SHA_B, DIGEST_B)
        self.service.approve(self.owner, other["id"])
        self.assertEqual(self.worker.run_next(self.project["id"], "production")["state"], "healthy")
        self.assertEqual(self.record(deployment["id"])["state"], "healthy")

    def test_a_member_cannot_promote(self):
        luvis = self.store.register_user("luis")
        invite = self.store.create_invite(self.owner, self.project["id"], "member")
        member = self.store.accept_invite(luvis["id"], invite["token"])
        deployment = self.approved()
        self.assertIsNotNone(member)
        with self.assertRaises(DomainError):
            self.service.approve(luvis["id"], deployment["id"])


if __name__ == "__main__":
    unittest.main()