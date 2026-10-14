import subprocess
import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.runner import Runner
from cshcli.workspace import Workspace


class FakeCoordinator:
    def __init__(self, leases=None):
        self.leases = dict(leases or {})
        self.validated = []
        self.renewed = []
        self.fail_validate = False
        self.fail_renew = False

    def validate_lease(self, project_id, lease_id, fence, resource=None):
        if self.fail_validate:
            raise DomainError(409, "lease_expired", "Lease has expired.")
        held = self.leases.get(lease_id)
        if held is None:
            raise DomainError(404, "lease_not_found", "Lease does not exist in this project.")
        if held["fence"] != fence:
            raise DomainError(409, "fence_mismatch", "The fencing token does not match the lease.")
        if resource is not None:
            covered = resource
            if not (covered == held["resource"]
                    or covered.startswith(held["resource"] + "/")
                    or held["resource"].startswith(covered + "/")):
                raise DomainError(409, "resource_not_leased",
                                  f"The lease covers {held['resource']}, not {covered}.")
        self.validated.append((project_id, lease_id, fence, resource))
        return dict(held, validated_at=1.0)

    def renew_lease(self, project_id, lease_id, fence, ttl=120):
        if self.fail_renew:
            raise DomainError(409, "lease_expired", "Lease has expired.")
        self.renewed.append((lease_id, fence, ttl))
        return {"id": lease_id, "fence": fence, "expires_at": ttl}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self._git(self.repo, "init", "-q")
        self._git(self.repo, "config", "user.email", "runner@example.invalid")
        self._git(self.repo, "config", "user.name", "Runner")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git(self.repo, "add", ".")
        self._git(self.repo, "commit", "-qm", "base")
        self.sha = self._git(self.repo, "rev-parse", "HEAD").strip()
        self.workspace = Workspace.create(self.repo, self.sha, "run-1",
                                          parent=Path(self.temp.name))
        self.addCleanup(self.workspace.close)

    def _git(self, repository, *arguments):
        return subprocess.run(["git", *arguments], cwd=repository, check=True,
                              capture_output=True, text=True).stdout

    def runner(self, coordinator=None, **keywords):
        coordinator = coordinator or FakeCoordinator({
            "lease-1": {"id": "lease-1", "resource": "file:src", "fence": 7},
        })
        runner = Runner(coordinator, self.workspace, project_id="p1",
                        run_id="run-1", **keywords)
        runner.track("lease-1", 7)
        return runner, coordinator

    def test_a_write_requires_a_live_lease(self):
        runner, coordinator = self.runner()
        runner.write_file("src/auth.py", b"x = 1\n", "lease-1", 7)
        self.assertEqual((self.workspace.read("src/auth.py")), b"x = 1\n")
        self.assertEqual(coordinator.validated,
                         [("p1", "lease-1", 7, "file:src/auth.py")])

    def test_an_expired_lease_stops_the_write(self):
        runner, coordinator = self.runner()
        coordinator.fail_validate = True
        with self.assertRaises(DomainError) as caught:
            runner.write_file("src/auth.py", b"x = 1\n", "lease-1", 7)
        self.assertEqual(caught.exception.code, "lease_expired")
        with self.assertRaises(Exception):
            self.workspace.read("src/auth.py")

    def test_a_path_outside_the_lease_is_refused_before_the_write(self):
        runner, coordinator = self.runner()
        with self.assertRaises(DomainError) as caught:
            runner.write_file("docs/other.md", b"leak\n", "lease-1", 7)
        self.assertEqual(caught.exception.code, "resource_not_leased")
        self.assertFalse((self.workspace.root / "docs" / "other.md").exists())

    def test_traversal_is_refused_before_any_coordinator_call(self):
        runner, coordinator = self.runner()
        with self.assertRaises(DomainError):
            runner.write_file("../outside.txt", b"escape", "lease-1", 7)
        self.assertEqual(coordinator.validated, [])
        self.assertFalse((Path(self.temp.name) / "outside.txt").exists())

    def test_an_untracked_fence_is_refused(self):
        runner, _ = self.runner()
        with self.assertRaises(DomainError) as caught:
            runner.write_file("src/auth.py", b"x = 1\n", "lease-1", 99)
        self.assertEqual(caught.exception.code, "fence_mismatch")

    def test_an_untracked_lease_is_refused(self):
        runner, _ = self.runner()
        with self.assertRaises(DomainError) as caught:
            runner.write_file("src/auth.py", b"x = 1\n", "lease-unknown", 7)
        self.assertEqual(caught.exception.code, "unknown_lease")

    def test_a_stopped_runner_writes_nothing(self):
        runner, _ = self.runner()
        runner.stop()
        with self.assertRaises(DomainError) as caught:
            runner.write_file("src/auth.py", b"x = 1\n", "lease-1", 7)
        self.assertEqual(caught.exception.code, "runner_stopped")

    def test_heartbeat_renews_every_tracked_lease(self):
        runner, coordinator = self.runner(heartbeat_seconds=30)
        self.assertFalse(runner.heartbeat_due())
        runner.clock = lambda: runner._last_beat + 30
        self.assertTrue(runner.heartbeat_due())
        runner.heartbeat()
        self.assertEqual(coordinator.renewed, [("lease-1", 7, 120)])

    def test_a_lost_heartbeat_stops_the_runner(self):
        runner, coordinator = self.runner()
        coordinator.fail_renew = True
        with self.assertRaises(DomainError):
            runner.heartbeat()
        self.assertTrue(runner.stopped)
        with self.assertRaises(DomainError) as caught:
            runner.write_file("src/auth.py", b"x = 1\n", "lease-1", 7)
        self.assertEqual(caught.exception.code, "runner_stopped")

    def test_removing_and_renaming_also_require_the_lease(self):
        runner, _ = self.runner()
        runner.write_file("src/a.py", b"a\n", "lease-1", 7)
        runner.rename("src/a.py", "src/b.py", "lease-1", 7)
        self.assertEqual(self.workspace.read("src/b.py"), b"a\n")
        runner.remove("src/b.py", "lease-1", 7)
        self.assertNotIn("src/b.py", runner.changed_paths())

    def test_the_runner_cannot_reach_a_host_decoy(self):
        decoy = Path(self.temp.name) / "host-secret.txt"
        decoy.write_text("do not read me\n", encoding="utf-8")
        runner, _ = self.runner()
        for candidate in ("../host-secret.txt", str(decoy), "..\\host-secret.txt"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(DomainError):
                    runner.read_file(candidate, "lease-1", 7)

    def test_the_runner_cannot_write_to_a_neighbour_checkout(self):
        neighbour = Path(self.temp.name) / "neighbour"
        neighbour.mkdir()
        (neighbour / "target.txt").write_text("original\n", encoding="utf-8")
        runner, _ = self.runner()
        with self.assertRaises(DomainError):
            runner.write_file(f"../neighbour/target.txt", b"stolen\n", "lease-1", 7)
        self.assertEqual((neighbour / "target.txt").read_text(encoding="utf-8"), "original\n")

    def test_the_runner_exposes_no_command_execution(self):
        runner, _ = self.runner()
        for name in ("run", "exec", "shell", "system", "popen", "subprocess"):
            self.assertFalse(hasattr(runner, name), f"Runner must not expose {name}.")

    def test_publish_after_a_new_generation_is_refused(self):
        from cshcli.integration import IntegrationGate
        from cshcli.store import Store

        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "coordinator.sqlite3")
            owner = store.register_user("ana")
            project = store.create_project(owner["id"], "demo")
            lease = store.acquire_leases(owner["id"], project["id"], "agent-1",
                                         ["file:src"], ttl=120)[0]
            generation = store.authorization_generation(owner["id"], project["id"])
            gate = IntegrationGate(store)
            store.revoke_authorization(owner["id"], project["id"], owner["id"])
            with self.assertRaises(DomainError) as caught:
                gate.accept_patch(owner["id"], project["id"], "run-1", generation,
                                  {"file:src": lease["fence"]}, self.sha, "a" * 40)
            self.assertEqual(caught.exception.code, "generation_stale")

    def test_heartbeat_seconds_must_be_sane(self):
        coordinator = FakeCoordinator()
        for value in (0, -1, 3601, True, "30"):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    Runner(coordinator, self.workspace, project_id="p1",
                           run_id="run-1", heartbeat_seconds=value)


if __name__ == "__main__":
    unittest.main()