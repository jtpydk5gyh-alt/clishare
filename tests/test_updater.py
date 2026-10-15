import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from cshcli.updater import (ARCHIVE_ROOT, UpdateUnavailable, compare,
                             fetch_checksums, install, newest_remote_version,
                             parse_version, verify)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        self.close()
        return False


def opener_for(body: bytes, status: int = 200):
    def opener(request, timeout=None):
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "no", {}, None)
        return FakeResponse(body)
    return opener


class VersionTests(unittest.TestCase):
    def test_a_normal_version_reads(self):
        self.assertEqual(parse_version("0.2.0"), (0, 2, 0))
        self.assertEqual(parse_version("v1.10.3"), (1, 10, 3))

    def test_nonsense_is_refused(self):
        for value in ("main", "0.2", "0.2.0.1", "0.2.x", "", None, 2):
            with self.subTest(value=value):
                with self.assertRaises(UpdateUnavailable):
                    parse_version(value)


class RemoteTests(unittest.TestCase):
    def test_no_published_release_reports_none(self):
        self.assertIsNone(newest_remote_version(opener_for(b"", status=404)))

    def test_a_release_returns_its_tag(self):
        body = json.dumps({"tag_name": "v0.3.0"}).encode()
        self.assertEqual(newest_remote_version(opener_for(body)), "v0.3.0")

    def test_a_network_failure_is_not_an_update(self):
        def broken(request, timeout=None):
            raise urllib.error.URLError("no route")
        with self.assertRaises(UpdateUnavailable):
            newest_remote_version(broken)

    def test_a_json_body_that_is_not_json_is_refused(self):
        with self.assertRaises(UpdateUnavailable):
            newest_remote_version(opener_for(b"<html>nope</html>"))


class CompareTests(unittest.TestCase):
    def test_the_same_version_is_current(self):
        report = compare("0.2.0", "v0.2.0")
        self.assertEqual(report["action"], "current")

    def test_an_older_install_is_an_update(self):
        self.assertEqual(compare("0.1.0", "v0.2.0")["action"], "update")

    def test_a_newer_install_is_ahead_and_says_why(self):
        report = compare("0.3.0", "v0.2.0")
        self.assertEqual(report["action"], "ahead")
        self.assertIn("main", report["detail"])

    def test_no_release_means_unknown_and_warns_about_main(self):
        report = compare("0.2.0", None)
        self.assertEqual(report["action"], "unknown")
        self.assertIn("main", report["detail"])

    def test_an_unreadable_remote_version_is_unknown_not_current(self):
        self.assertEqual(compare("0.2.0", "nightly")["action"], "unknown")

    def test_the_report_never_promises_anything_by_default(self):
        for published in (None, "v0.2.0", "v0.3.0", "v0.1.0", "garbage"):
            with self.subTest(published=published):
                report = compare("0.2.0", published)
                self.assertNotIn(report["action"], ("installing", "installing_anything"))
                self.assertEqual(report["from_main"], True)


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_wheel_file_verifies(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        digest = hashlib.sha256(b"contents").hexdigest()
        self.assertTrue(verify(target, digest))
        self.assertTrue(verify(target, digest.upper()))

    def test_a_tampered_file_does_not_verify(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        digest = hashlib.sha256(b"contents").hexdigest()
        target.write_bytes(b"tampered")
        self.assertFalse(verify(target, digest))

    def test_checksums_are_parsed(self):
        body = ("f476879a85e83745c9b36ebe54ee4b6a0ddbed7e9bad4e78f18b5105b36b8fe6  "
                "cshcli-0.2.0-py3-none-any.whl\n"
                "short  nonsense.txt\n\n").encode()
        parsed = fetch_checksums(ARCHIVE_ROOT.replace("main.zip", "SHA256SUMS"),
                                 opener_for(body))
        self.assertEqual(list(parsed), ["cshcli-0.2.0-py3-none-any.whl"])

    def test_a_download_failure_is_refused(self):
        def broken(request, timeout=None):
            raise urllib.error.URLError("no route")
        with self.assertRaises(UpdateUnavailable):
            fetch_checksums("https://example.invalid/SHA256SUMS", broken)

    def test_installing_a_mismatch_removes_the_file(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"tampered")
        with self.assertRaises(UpdateUnavailable) as caught:
            install(target, hashlib.sha256(b"contents").hexdigest())
        self.assertIn("nothing was installed", str(caught.exception))
        self.assertFalse(target.exists(), "a failed verification must leave no file behind")

    def test_installing_without_a_checksum_is_refused(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        with self.assertRaises(UpdateUnavailable):
            install(target, "")


if __name__ == "__main__":
    unittest.main()