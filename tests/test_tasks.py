import tempfile
import threading
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.store import Store
from cshcli.tasks import BLOCKED, CANCELLED, MERGED, QUEUED, RUNNING, TaskService


SHA = "a" * 40
SHA_B = "b" * 40


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.ana = self.store.register_user("ana")
        self.luis = self.store.register_user("luis")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.tasks = TaskService(self.store)

    def create(self, title, dependencies=None, resources=None, user=None):
        return self.tasks.create(
            user or self.ana["id"], self.project["id"], title,
            dependencies, resources)

    def test_a_task_with_no_dependencies_is_queued(self):
        task = self.create("first", resources=["file:src"])
        self.assertEqual(task["state"], QUEUED)
        self.assertEqual(task["resources"], ["file:src"])
        self.assertEqual(task["dependencies"], [])

    def test_a_task_with_dependencies_starts_blocked(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        self.assertEqual(second["state"], BLOCKED)

    def test_a_dependency_from_another_project_is_refused(self):
        other = self.store.create_project(self.luis["id"], "other")
        foreign = self.tasks.create(self.luis["id"], other["id"], "foreign")
        with self.assertRaises(DomainError) as caught:
            self.create("bad", [foreign["id"]])
        self.assertEqual(caught.exception.code, "task_not_found")

    def test_a_direct_cycle_is_refused(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        with self.assertRaises(DomainError) as caught:
            self._force_dependency(first["id"], second["id"])
        self.assertEqual(caught.exception.code, "dependency_cycle")

    def _force_dependency(self, task_id, depends_on):
        with self.store._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO task_dependencies(task_id, depends_on) VALUES (?, ?)",
                (task_id, depends_on))
            self.tasks._assert_acyclic(connection, self.project["id"])

    def test_a_longer_cycle_is_refused(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        third = self.create("third", [second["id"]], ["file:c"])
        with self.assertRaises(DomainError) as caught:
            self._force_dependency(first["id"], third["id"])
        self.assertEqual(caught.exception.code, "dependency_cycle")

    def test_a_dependent_stays_blocked_while_its_dependency_is_in_review(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        self.tasks.claim(self.ana["id"], self.project["id"], first["id"], "agent-1")
        self.tasks.complete(self.ana["id"], self.project["id"], first["id"], SHA)
        self.assertEqual(self.tasks.get(self.ana["id"], self.project["id"], second["id"])["state"], BLOCKED)
        with self.assertRaises(DomainError) as caught:
            self.tasks.claim(self.ana["id"], self.project["id"], second["id"], "agent-2")
        self.assertEqual(caught.exception.code, "dependencies_pending")

    def test_claiming_takes_the_leases_and_starts_in_one_decision(self):
        task = self.create("work", resources=["file:src/auth.py"])
        claimed = self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        self.assertEqual(claimed["state"], RUNNING)
        self.assertEqual(claimed["assignee_id"], "agent-1")
        leases = self.store.list_leases(self.ana["id"], self.project["id"])
        self.assertEqual([item["resource"] for item in leases], ["file:src/auth.py"])

    def test_claiming_takes_no_lease_when_a_resource_is_busy(self):
        first = self.create("one", resources=["file:src"])
        second = self.create("two", resources=["file:src/auth.py"])
        self.tasks.claim(self.ana["id"], self.project["id"], first["id"], "agent-1")
        with self.assertRaises(DomainError) as caught:
            self.tasks.claim(self.ana["id"], self.project["id"], second["id"], "agent-2")
        self.assertEqual(caught.exception.code, "lease_conflict")
        self.assertEqual(self.tasks.get(self.ana["id"], self.project["id"], second["id"])["state"], QUEUED)
        holders = {item["agent_id"] for item in self.store.list_leases(self.ana["id"], self.project["id"])}
        self.assertEqual(holders, {"agent-1"})

    def test_a_task_waits_for_its_dependencies(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        with self.assertRaises(DomainError) as caught:
            self.tasks.claim(self.ana["id"], self.project["id"], second["id"], "agent-1")
        self.assertEqual(caught.exception.code, "dependencies_pending")
        self.assertEqual(self.store.list_leases(self.ana["id"], self.project["id"]), [])

    def test_a_dependent_unblocks_only_when_the_dependency_merges(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        self.tasks.claim(self.ana["id"], self.project["id"], first["id"], "agent-1")
        self.tasks.complete(self.ana["id"], self.project["id"], first["id"], SHA)
        self.assertEqual(self.tasks.get(self.ana["id"], self.project["id"], second["id"])["state"], BLOCKED)
        self.tasks.mark(self.ana["id"], self.project["id"], first["id"], MERGED)
        self.assertEqual(self.tasks.get(self.ana["id"], self.project["id"], second["id"])["state"], QUEUED)
        claimed = self.tasks.claim(self.ana["id"], self.project["id"], second["id"], "agent-2")
        self.assertEqual(claimed["state"], RUNNING)

    def test_a_dependent_stays_blocked_when_its_dependency_is_cancelled(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"]], ["file:b"])
        self.tasks.cancel(self.ana["id"], self.project["id"], first["id"])
        state = self.tasks.get(self.ana["id"], self.project["id"], second["id"])["state"]
        self.assertEqual(state, BLOCKED)
        with self.assertRaises(DomainError):
            self.tasks.claim(self.ana["id"], self.project["id"], second["id"], "agent-1")

    def test_a_task_cannot_be_claimed_twice(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        with self.assertRaises(DomainError) as caught:
            self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-2")
        self.assertEqual(caught.exception.code, "task_not_claimable")

    def test_a_cancelled_task_cannot_be_claimed(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.cancel(self.ana["id"], self.project["id"], task["id"])
        with self.assertRaises(DomainError) as caught:
            self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        self.assertEqual(caught.exception.code, "task_not_claimable")

    def test_a_finished_task_keeps_its_outcome(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        self.tasks.mark(self.ana["id"], self.project["id"], task["id"], MERGED)
        with self.assertRaises(DomainError):
            self.tasks.mark(self.ana["id"], self.project["id"], task["id"], "queued")
        with self.assertRaises(DomainError):
            self.tasks.cancel(self.ana["id"], self.project["id"], task["id"])

    def test_completing_records_both_shas_and_moves_to_review(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        done = self.tasks.complete(self.ana["id"], self.project["id"], task["id"], SHA, SHA_B)
        self.assertEqual(done["state"], "review")
        self.assertEqual(done["commit_sha"], SHA)
        self.assertEqual(done["base_sha"], SHA_B)

    def test_completing_refuses_a_sha_that_is_not_one(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        for value in ("short", "z" * 40, 42, ""):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    self.tasks.complete(self.ana["id"], self.project["id"], task["id"], value)

    def test_a_non_member_cannot_create_or_claim(self):
        with self.assertRaises(DomainError):
            self.tasks.create(self.luis["id"], self.project["id"], "intruder", None, ["file:a"])
        task = self.create("work", resources=["file:a"])
        with self.assertRaises(DomainError):
            self.tasks.claim(self.luis["id"], self.project["id"], task["id"], "agent-9")

    def test_eleven_agents_racing_for_two_tasks_leave_one_holder(self):
        free = self.create("free", resources=["file:shared"])
        held = self.create("held", resources=["file:src"])
        self.tasks.claim(self.ana["id"], self.project["id"], held["id"], "incumbent")
        outcomes = []
        barrier = threading.Barrier(11)

        def attempt(index):
            barrier.wait()
            try:
                outcomes.append(self.tasks.claim(
                    self.ana["id"], self.project["id"], free["id"], f"agent-{index}"))
            except DomainError:
                outcomes.append(None)

        threads = [threading.Thread(target=attempt, args=(index,)) for index in range(11)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [item for item in outcomes if item is not None]
        self.assertEqual(len(winners), 1, "exactly one agent may hold the task")
        leases = self.store.list_leases(self.ana["id"], self.project["id"])
        self.assertEqual(len(leases), 2)

    def test_a_reviewer_outside_the_project_cannot_move_a_task(self):
        task = self.create("work", resources=["file:a"])
        with self.assertRaises(DomainError):
            self.tasks.mark(self.luis["id"], self.project["id"], task["id"], MERGED)

    def test_cancelling_releases_nothing_by_itself(self):
        task = self.create("work", resources=["file:a"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        self.tasks.cancel(self.ana["id"], self.project["id"], task["id"])
        self.assertEqual(len(self.store.list_leases(self.ana["id"], self.project["id"])), 1)

    def test_unknown_states_are_refused(self):
        task = self.create("work", resources=["file:a"])
        for state in ("done", "", None, 1, CANCELLED + "x"):
            with self.subTest(state=state):
                with self.assertRaises(DomainError):
                    self.tasks.mark(self.ana["id"], self.project["id"], task["id"], state)

    def test_duplicate_dependencies_are_collapsed(self):
        first = self.create("first", resources=["file:a"])
        second = self.create("second", [first["id"], first["id"]], ["file:b"])
        self.assertEqual(second["dependencies"], [first["id"]])


if __name__ == "__main__":
    unittest.main()