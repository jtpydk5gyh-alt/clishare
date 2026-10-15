import os
import tempfile
import unittest
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.onboarding import PROVIDER_VARIABLES, Keyring, next_step


class KeyringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1000.0]
        self.root = Path(self.temp.name)
        self.keyring = Keyring(self.root, clock=lambda: self.now[0])

    def test_a_key_is_stored_and_read_back(self):
        self.keyring.set("openai", "sk-example-value")
        self.assertEqual(self.keyring.get("openai"), "sk-example-value")

    def test_a_missing_key_is_none(self):
        self.assertIsNone(self.keyring.get("anthropic"))

    def test_an_empty_key_is_refused(self):
        for value in ("", "   ", None, 42):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    self.keyring.set("openai", value)

    def test_a_provider_name_is_required(self):
        for value in ("", "   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    self.keyring.set(value, "sk-example")

    def test_describe_never_includes_the_secret(self):
        self.keyring.set("openai", "sk-super-secret-value")
        report = self.keyring.describe("openai")
        rendered = str(report)
        self.assertNotIn("sk-super-secret-value", rendered)
        self.assertTrue(report["configured"])
        self.assertEqual(report["source"], "keyring")
        self.assertEqual(report["length"], len("sk-super-secret-value"))

    def test_the_environment_wins_over_the_file(self):
        self.keyring.set("openai", "from-the-file")
        os.environ[PROVIDER_VARIABLES["openai"]] = "from-the-environment"
        self.addCleanup(os.environ.pop, PROVIDER_VARIABLES["openai"], None)
        secret, source = self.keyring.resolve("openai")
        self.assertEqual(secret, "from-the-environment")
        self.assertEqual(source, "environment")

    def test_an_empty_environment_variable_falls_back_to_the_file(self):
        self.keyring.set("openai", "from-the-file")
        os.environ[PROVIDER_VARIABLES["openai"]] = "   "
        self.addCleanup(os.environ.pop, PROVIDER_VARIABLES["openai"], None)
        secret, source = self.keyring.resolve("openai")
        self.assertEqual(secret, "from-the-file")
        self.assertEqual(source, "keyring")

    def test_nothing_configured_reports_missing(self):
        self.assertEqual(self.keyring.resolve("minimax"), (None, "missing"))
        report = self.keyring.describe("minimax")
        self.assertFalse(report["configured"])
        self.assertEqual(report["length"], 0)

    def test_a_provider_without_a_variable_still_works(self):
        self.keyring.set("codex", "nothing-secret-but-set")
        secret, source = self.keyring.resolve("codex")
        self.assertEqual(source, "keyring")

    def test_dropping_a_key_that_is_not_there_is_false(self):
        self.assertFalse(self.keyring.drop("openai"))
        self.keyring.set("openai", "sk-example-value")
        self.assertTrue(self.keyring.drop("openai"))
        self.assertIsNone(self.keyring.get("openai"))

    def test_the_file_survives_a_reopen(self):
        self.keyring.set("openai", "sk-example-value")
        self.assertEqual(Keyring(self.root).get("openai"), "sk-example-value")

    def test_opening_the_keyring_twice_does_not_erase_it(self):
        self.keyring.set("openai", "first")
        self.keyring.set("anthropic", "second")
        for _ in range(3):
            reopened = Keyring(self.root)
            self.assertEqual(reopened.get("openai"), "first")
            self.assertEqual(reopened.get("anthropic"), "second")

    def test_the_file_is_readable_only_by_this_user(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions are the guarantee; Windows has none here")
        self.keyring.set("openai", "sk-example-value")
        self.assertTrue(self.keyring.permissions_are_private())

    def test_a_corrupt_file_does_not_crash(self):
        self.keyring.path.write_text("not json at all", encoding="utf-8")
        self.assertIsNone(self.keyring.get("openai"))
        self.assertEqual(self.keyring.resolve("openai"), (None, "missing"))

    def test_one_provider_never_reveals_another(self):
        self.keyring.set("openai", "openai-secret")
        self.keyring.set("anthropic", "anthropic-secret")
        for provider in ("openai", "anthropic", "google"):
            with self.subTest(provider=provider):
                self.assertNotIn("openai-secret", str(self.keyring.describe(provider)))
                self.assertNotIn("anthropic-secret", str(self.keyring.describe(provider)))


class NextStepTests(unittest.TestCase):
    def test_the_coordinator_comes_first(self):
        step = next_step(False, False, False, "openai", False)
        self.assertEqual(step["step"], "serve")

    def test_then_the_identity(self):
        step = next_step(True, False, False, "openai", False)
        self.assertEqual(step["step"], "identity")
        self.assertTrue(step["question"])

    def test_then_the_project(self):
        step = next_step(True, True, False, "openai", False)
        self.assertEqual(step["step"], "project")

    def test_then_the_key(self):
        step = next_step(True, True, True, "openai", False)
        self.assertEqual(step["step"], "provider")
        self.assertIn("openai", step["question"])

    def test_and_then_it_is_done(self):
        step = next_step(True, True, True, "openai", True)
        self.assertEqual(step["step"], "ready")
        self.assertIsNone(step["question"])

    def test_every_step_says_what_to_run(self):
        for arguments in ((False, False, False, "openai", False),
                          (True, False, False, "openai", False),
                          (True, True, False, "openai", False),
                          (True, True, True, "openai", False),
                          (True, True, True, "openai", True)):
            with self.subTest(arguments=arguments):
                step = next_step(*arguments)
                self.assertTrue(str(step["do"]).startswith("cshcli"))


if __name__ == "__main__":
    unittest.main()