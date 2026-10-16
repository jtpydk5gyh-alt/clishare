import http.client
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from cshcli.deploy import DeployService, DeployWorker, InProcessDestination
from cshcli.policy import Policy
from cshcli.server import make_server
from cshcli.store import Store
from cshcli.tasks import MERGED, RUNNING, TaskService


class CoordinatorOutageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "coordinator.sqlite3"
        self.store = Store(self.database)
        self.ana = self.store.register_user("ana")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.tasks = TaskService(self.store)
        self.started = []

    def stop(self):
        for process in reversed(self.started):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(10)

    def test_a_stopped_coordinator_leaves_the_task_as_it_was(self):
        coordinator = make_server(self.database, "127.0.0.1", 0)
        port = coordinator.server_address[1]
        thread = threading.Thread(target=coordinator.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(coordinator.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(coordinator.shutdown)

        task = self.tasks.create(self.ana["id"], self.project["id"], "long job", None, ["file:src"])
        self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1")
        self.tasks.create(self.ana["id"], self.project["id"], "queued", None, ["file:other"])

        coordinator.shutdown()
        coordinator.server_close()
        thread.join(5)

        reopened = Store(self.database)
        running = reopened.get_task(self.ana["id"], self.project["id"], task["id"]) \
            if hasattr(reopened, "get_task") else self.tasks.get(self.ana["id"], self.project["id"], task["id"])
        self.assertEqual(running["state"], RUNNING,
                         "an interrupted run stays running; it is not silently finished")
        states = sorted(item["state"] for item in self.tasks.list(self.ana["id"], self.project["id"]))
        self.assertEqual(states, sorted([RUNNING, "queued"]))

    def test_a_task_resumes_after_the_coordinator_comes_back(self):
        coordinator = make_server(self.database, "127.0.0.1", 0)
        thread = threading.Thread(target=coordinator.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(coordinator.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(coordinator.shutdown)

        connection = http.client.HTTPConnection("127.0.0.1", coordinator.server_address[1],
                                                timeout=5)
        body = json_body({"name": "bruno"})
        connection.request("POST", "/v1/users", body,
                           {"Content-Type": "application/json", "Accept": "application/json"})
        answer = connection.getresponse()
        self.assertEqual(answer.status, 201)
        created = json_load(answer.read())
        connection.close()

        coordinator.shutdown()
        coordinator.server_close()
        thread.join(5)

        again = make_server(self.database, "127.0.0.1", 0)
        second = threading.Thread(target=again.serve_forever, daemon=True)
        second.start()
        self.addCleanup(again.server_close)
        self.addCleanup(second.join, 5)
        self.addCleanup(again.shutdown)

        connection = http.client.HTTPConnection("127.0.0.1", again.server_address[1], timeout=5)
        token = created["data"]["token"]
        connection.request("GET", "/v1/projects", None,
                           {"Authorization": "Bearer " + token, "Accept": "application/json"})
        answer = connection.getresponse()
        self.assertEqual(answer.status, 200)
        self.assertIn("data", json_load(answer.read()))
        connection.close()

    def test_the_database_survives_being_opened_again(self):
        self.store.create_project(self.ana["id"], "second")
        reopened = Store(self.database)
        self.assertEqual(len(self.projects_of(reopened)), 2)

    def projects_of(self, store):
        with store._connection() as connection:
            return connection.execute("SELECT id FROM projects").fetchall()

    def test_a_separate_process_reads_what_this_one_wrote(self):
        self.store.create_project(self.ana["id"], "written-here")
        script = (
            "import sqlite3,sys;"
            "c=sqlite3.connect(sys.argv[1]);"
            "print(c.execute('SELECT name FROM projects').fetchall())"
        )
        result = subprocess.run([sys.executable, "-c", script, str(self.database)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("written-here", result.stdout)

    def test_a_failed_transaction_leaves_nothing_half_written(self):
        try:
            with self.store._connection(write=True) as connection:
                connection.execute(
                    "INSERT INTO projects(id, name, owner_id)"
                    " VALUES ('doomed', 'doomed', ?)", (self.ana["id"],))
                raise RuntimeError("the process dies here")
        except RuntimeError:
            pass
        with self.store._connection() as connection:
            present = connection.execute(
                "SELECT 1 FROM projects WHERE id = 'doomed'").fetchone()
        self.assertIsNone(present, "an aborted batch must leave nothing behind")


class ExpiryDrillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1000.0]
        self.store = Store(Path(self.temp.name) / "c.sqlite3", clock=lambda: self.now[0])
        self.ana = self.store.register_user("ana")
        self.luis = self.store.register_user("luis")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.tasks = TaskService(self.store, clock=lambda: self.now[0])

    def test_a_dead_agents_lease_lets_a_second_agent_in(self):
        task = self.tasks.create(self.ana["id"], self.project["id"], "work", None, ["file:src"])
        first = self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1", ttl=60)
        self.assertEqual(first["state"], RUNNING)

        self.now[0] += 61

        fresh = self.tasks.create(self.ana["id"], self.project["id"], "next", None, ["file:src"])
        second = self.tasks.claim(self.ana["id"], self.project["id"], fresh["id"], "agent-2", ttl=60)
        self.assertEqual(second["state"], RUNNING)
        holders = {item["agent_id"] for item in self.store.list_leases(self.ana["id"], self.project["id"])}
        self.assertEqual(holders, {"agent-2"}, "the dead agent's lease must not linger")

    def test_the_stale_holder_cannot_renew_or_release_the_new_lease(self):
        task = self.tasks.create(self.ana["id"], self.project["id"], "work", None, ["file:src"])
        stale = self.tasks.claim(self.ana["id"], self.project["id"], task["id"], "agent-1", ttl=60)
        self.now[0] += 61
        fresh = self.tasks.create(self.ana["id"], self.project["id"], "next", None, ["file:src"])
        second = self.tasks.claim(self.ana["id"], self.project["id"], fresh["id"], "agent-2", ttl=60)
        with self.assertRaises(Exception):
            self.store.renew_lease(self.ana["id"], self.project["id"],
                                   second["id"], stale["assignee_id"] and 1, 60)
        with self.assertRaises(Exception):
            self.store.release_lease(self.ana["id"], self.project["id"], second["id"], 1)


class InterruptedDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.ana = self.store.register_user("ana")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.service = DeployService(self.store)
        self.destination = InProcessDestination()
        self.worker = DeployWorker(self.store, self.destination)

    def approved(self, key="rel-1", digest="sha256:" + "1" * 64):
        deployment = self.service.enqueue(self.ana["id"], self.project["id"], "prod",
                                          "a" * 40, digest, key)
        self.service.record_checks(self.ana["id"], deployment["id"], "a" * 40, digest)
        return self.service.approve(self.ana["id"], deployment["id"])

    def test_re_running_an_interrupted_deploy_is_idempotent(self):
        first = self.approved()
        self.worker.run_next(self.project["id"], "prod")
        self.assertEqual(
            self.service.get(self.ana["id"], self.project["id"], first["id"])["state"],
            "healthy")
        same = self.service.enqueue(self.ana["id"], self.project["id"], "prod",
                                    "a" * 40, "sha256:" + "1" * 64, "rel-1")
        self.assertEqual(same["id"], first["id"], "the same key never creates a second deployment")
        self.assertEqual(self.worker.run_next(self.project["id"], "prod")["state"], "idle")

    def test_a_deploy_stopped_before_health_leaves_nothing_healthy(self):
        deployment = self.approved()

        def die_on_promote(change):
            raise KeyboardInterrupt("the process is going down")

        self.destination.promote = die_on_promote
        with self.assertRaises(KeyboardInterrupt):
            self.worker.run_next(self.project["id"], "prod")
        state = self.service.get(self.ana["id"], self.project["id"], deployment["id"])
        self.assertNotEqual(state["state"], "healthy")


def json_body(payload):
    import json
    return json.dumps(payload).encode("utf-8")


def json_load(raw):
    import json
    return json.loads(raw.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()