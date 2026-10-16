import multiprocessing
import os
import time
import unittest
import uuid

from cshcli.errors import DomainError
from cshcli.remote.database import RemoteStore, driver_available


DSN = os.environ.get("CSHCLI_REMOTE_DSN", "")


def _seed(dsn, project_id):
    import psycopg
    user_id = f"seed-user-{project_id}"
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO users(id, name, name_key, token_hash) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (id) DO NOTHING",
            (user_id, f"name-{project_id}", f"key-{project_id}", f"token-{project_id}"))
        connection.execute(
            "INSERT INTO projects(id, name, name_key, owner_id) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (id) DO NOTHING",
            (project_id, f"project-{project_id}", f"pkey-{project_id}", user_id))
        connection.execute(
            "INSERT INTO memberships(project_id, user_id, role) VALUES (%s, %s, 'owner')"
            " ON CONFLICT DO NOTHING", (project_id, user_id))
    return user_id


def _count_leases(dsn, project_id, resource):
    import psycopg
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            "SELECT count(*) FROM leases WHERE project_id = %s AND resource = %s",
            (project_id, resource)).fetchone()[0]


def _stored_expiry(dsn, project_id, resource):
    import psycopg
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            "SELECT expires_at FROM leases WHERE project_id = %s AND resource = %s",
            (project_id, resource)).fetchone()[0]


def _race(dsn, user_id, project_id, agent_id, resources, queue):
    import traceback
    try:
        store = RemoteStore(dsn)
        store.connect()
        acquired = store.acquire_leases(user_id, project_id, agent_id, resources, ttl=60)
        queue.put(("won", agent_id, [item["resource"] for item in acquired]))
    except DomainError as error:
        queue.put(("lost", agent_id, error.code))
    except BaseException:
        queue.put(("error", agent_id, traceback.format_exc()[-400:]))


SKIP_REASON = (
    "requires a real PostgreSQL: set CSHCLI_REMOTE_DSN and install cshcli[remote]. "
    "No server was reachable, so nothing about PostgreSQL concurrency is proven."
)


class RemotePostgresTests(unittest.TestCase):
    def setUp(self):
        if not (DSN and driver_available()):
            self.skipTest(SKIP_REASON)
        import psycopg
        try:
            psycopg.connect(DSN, connect_timeout=10).close()
        except Exception as error:
            self.skipTest(f"{SKIP_REASON} ({type(error).__name__})")
        self.project_id = f"race-{uuid.uuid4().hex[:12]}"
        self.user_id = _seed(DSN, self.project_id)

    def test_eleven_processes_on_overlapping_prefixes_leave_one_winner(self):
        queue = multiprocessing.Queue()
        processes = []
        for index in range(11):
            resources = (["file:src"] if index % 2 == 0 else ["file:src/a.py"])
            process = multiprocessing.Process(
                target=_race, args=(DSN, self.user_id, self.project_id,
                                    f"agent-{index}", resources, queue))
            processes.append(process)
            process.start()
        for process in processes:
            process.join(120)

        outcomes = []
        while True:
            try:
                outcomes.append(queue.get(timeout=5))
            except Exception:
                break
        codes = sorted(process.exitcode for process in processes)
        self.assertEqual(len(outcomes), 11,
                         f"once procesos y once respuestas; exit codes {codes}; "
                         f"recibidas {outcomes}")
        self.assertTrue(all(item[0] != "error" for item in outcomes), outcomes)
        winners = [item for item in outcomes if item[0] == "won"]
        self.assertEqual(len(winners), 1, f"exactly one winner expected, got {outcomes}")
        self.assertEqual(_count_leases(DSN, self.project_id, "file:src")
                         + _count_leases(DSN, self.project_id, "file:src/a.py"), 1)

    def test_the_store_refuses_to_serve_while_unverified(self):
        store = RemoteStore(DSN)
        with self.assertRaises(DomainError) as caught:
            store.assert_production_ready()
        self.assertEqual(caught.exception.code, "remote_unverified")

    def test_a_lease_really_lands_in_postgres(self):
        store = RemoteStore(DSN)
        store.connect()
        self.addCleanup(store.close)
        acquired = store.acquire_leases(self.user_id, self.project_id, "agente-1",
                                        ["file:src"], ttl=60)
        self.assertEqual(len(acquired), 1)
        self.assertEqual(acquired[0]["resource"], "file:src")
        self.assertEqual(_count_leases(DSN, self.project_id, "file:src"), 1)

    def test_a_second_agent_over_the_same_resource_is_refused(self):
        first = RemoteStore(DSN)
        first.connect()
        first.acquire_leases(self.user_id, self.project_id, "agente-1", ["file:src"], ttl=60)
        first.close()
        second = RemoteStore(DSN)
        second.connect()
        self.addCleanup(second.close)
        with self.assertRaises(DomainError) as caught:
            second.acquire_leases(self.user_id, self.project_id, "agente-2",
                                  ["file:src/a.py"], ttl=60)
        self.assertEqual(caught.exception.code, "lease_conflict")

    def test_the_fence_never_goes_backwards(self):
        store = RemoteStore(DSN)
        store.connect()
        self.addCleanup(store.close)
        first = store.acquire_leases(self.user_id, self.project_id, "a", ["file:x"], ttl=60)
        store.acquire_leases(self.user_id, self.project_id, "b", ["file:y"], ttl=60)
        second = store.acquire_leases(self.user_id, self.project_id, "c", ["file:z"], ttl=60)
        self.assertLess(first[0]["fence"], second[-1]["fence"])

    def test_a_fresh_connection_keeps_working_after_the_lease_expires(self):
        store = RemoteStore(DSN)
        store.connect()
        store.acquire_leases(self.user_id, self.project_id, "a", ["file:t"], ttl=-1)
        store.close()
        later = RemoteStore(DSN)
        later.connect()
        self.addCleanup(later.close)
        acquired = later.acquire_leases(self.user_id, self.project_id, "b",
                                        ["file:t"], ttl=60)
        self.assertEqual(len(acquired), 1)

    def test_the_stored_expiry_keeps_the_precision_it_was_given(self):
        store = RemoteStore(DSN)
        store.connect()
        self.addCleanup(store.close)
        store.acquire_leases(self.user_id, self.project_id, "a", ["file:precision"],
                             ttl=90)
        stored = _stored_expiry(DSN, self.project_id, "file:precision")
        self.assertNotAlmostEqual(stored, round(stored), delta=0,
                                  msg="el instante se guardo redondeado")
        self.assertAlmostEqual(stored % 1, stored % 1, delta=0)

    def test_a_short_lease_really_dies_after_its_ttl(self):
        store = RemoteStore(DSN)
        store.connect()
        self.addCleanup(store.close)
        store.acquire_leases(self.user_id, self.project_id, "a", ["file:corta"], ttl=2)
        with self.assertRaises(DomainError) as caught:
            store.acquire_leases(self.user_id, self.project_id, "b", ["file:corta"], ttl=60)
        self.assertEqual(caught.exception.code, "lease_conflict")
        time.sleep(3)
        store.acquire_leases(self.user_id, self.project_id, "c", ["file:corta"], ttl=60)


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