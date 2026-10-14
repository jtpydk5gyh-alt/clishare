import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.store import Store


class ValidateLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.owner = self.store.register_user("ana")
        self.outsider = self.store.register_user("luis")
        self.project = self.store.create_project(self.owner["id"], "demo")
        self.lease = self.store.acquire_leases(
            self.owner["id"], self.project["id"], "a1", ["file:src"], ttl=120)[0]

    def validate(self, user_id=None, fence=None, resource=None):
        return self.store.validate_lease(
            user_id or self.owner["id"], self.project["id"], self.lease["id"],
            self.lease["fence"] if fence is None else fence, resource)

    def test_a_live_lease_validates(self):
        report = self.validate(resource="file:src/auth.py")
        self.assertEqual(report["resource"], "file:src")
        self.assertIn("validated_at", report)

    def test_an_expired_lease_does_not_validate(self):
        clock = self.store.clock
        self.store.clock = lambda: clock() + 1000
        try:
            with self.assertRaises(DomainError) as caught:
                self.validate()
        finally:
            self.store.clock = clock
        self.assertEqual(caught.exception.code, "lease_expired")

    def test_a_wrong_fence_does_not_validate(self):
        with self.assertRaises(DomainError) as caught:
            self.validate(fence=self.lease["fence"] + 1)
        self.assertEqual(caught.exception.code, "fence_mismatch")

    def test_a_non_member_cannot_validate_a_lease_of_another_project(self):
        other = self.store.create_project(self.outsider["id"], "other")
        with self.assertRaises(DomainError):
            self.store.validate_lease(
                self.outsider["id"], other["id"], self.lease["id"], self.lease["fence"])

    def test_a_resource_outside_the_lease_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.validate(resource="file:docs")
        self.assertEqual(caught.exception.code, "resource_not_leased")

    def test_a_parent_of_the_lease_is_covered(self):
        self.validate(resource="file:src")

    def test_an_unknown_lease_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.store.validate_lease(self.owner["id"], self.project["id"],
                                      "no-such-lease", 1)
        self.assertEqual(caught.exception.code, "lease_not_found")


if __name__ == "__main__":
    unittest.main()