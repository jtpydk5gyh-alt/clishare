"""The concurrency test the plan forbids mocking.

Against a real PostgreSQL this launches eleven independent processes that race
for `file:src` and `file:src/a.py`, and requires exactly one winner. A mock
would prove nothing about `SELECT ... FOR UPDATE`, so when no server is
reachable this test skips and says so. Deleting it or replacing it with a mock
would be the one thing the plan explicitly prohibits.

Run it with:

    CSHCLI_REMOTE_DSN=postgresql://... python -m unittest tests.test_remote_postgres
"""

import multiprocessing
import os
import unittest

from cshcli.errors import DomainError
from cshcli.remote.database import RemoteStore, driver_available


DSN = os.environ.get("CSHCLI_REMOTE_DSN", "")


def _race(dsn, project_id, agent_id, resources, queue):
    try:
        store = RemoteStore(dsn)
        store.connect()
        acquired = store.acquire_leases("race-user", project_id, agent_id, resources, ttl=60)
        queue.put(("won", agent_id, [item["resource"] for item in acquired]))
    except DomainError as error:
        queue.put(("lost", agent_id, error.code))
    except Exception as error:  # noqa: BLE001
        queue.put(("error", agent_id, type(error).__name__))


SKIP_REASON = (
    "requires a real PostgreSQL: set CSHCLI_REMOTE_DSN and install cshcli[remote]. "
    "No server was reachable, so nothing about PostgreSQL concurrency is proven."
)


class RemotePostgresTests(unittest.TestCase):
    def setUp(self):
        if not (DSN and driver_available()):
            self.skipTest(SKIP_REASON)

    def test_eleven_processes_on_overlapping_prefixes_leave_one_winner(self):
        from cshcli.store import Store
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            local = Store(Path(temp) / "seed.sqlite3")
            owner = local.register_user("owner")
            project = local.create_project(owner["id"], "race")

        queue = multiprocessing.Queue()
        processes = []
        for index in range(11):
            resources = (["file:src"] if index % 2 == 0 else ["file:src/a.py"])
            process = multiprocessing.Process(
                target=_race, args=(DSN, project["id"], f"agent-{index}", resources, queue))
            processes.append(process)
            process.start()
        for process in processes:
            process.join(60)

        outcomes = [queue.get() for _ in processes]
        winners = [item for item in outcomes if item[0] == "won"]
        self.assertEqual(len(winners), 1, f"exactly one winner expected, got {outcomes}")
        self.assertTrue(all(item[0] != "error" for item in outcomes), outcomes)

    def test_the_store_refuses_to_serve_while_unverified(self):
        store = RemoteStore(DSN)
        with self.assertRaises(DomainError) as caught:
            store.assert_production_ready()
        self.assertEqual(caught.exception.code, "remote_unverified")


class VerificationReportingTests(unittest.TestCase):
    def test_it_reports_unverified_without_a_server(self):
        from cshcli.remote.database import UNVERIFIED, verification
        report = verification(None)
        self.assertEqual(report["state"], UNVERIFIED)
        self.assertIn(report["reason"], {"driver_not_installed", "no_dsn",
                                         "concurrency_unproven"})

    def test_verification_never_claims_verified_on_its_own(self):
        from cshcli.remote.database import VERIFIED, verification
        for dsn in (None, "", "postgresql://localhost/x"):
            self.assertNotEqual(verification(dsn)["state"], VERIFIED)

    def test_the_module_never_imports_the_driver_at_import_time(self):
        import sys
        import importlib
        module = "cshcli.remote.database"
        importlib.import_module(module)
        if not driver_available():
            self.assertNotIn("psycopg", sys.modules)


if __name__ == "__main__":
    unittest.main()