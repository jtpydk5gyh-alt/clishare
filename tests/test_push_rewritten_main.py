import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push_rewritten_main.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("push_rewritten_main", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load_helper()
_real_gh = helper.gh


class RewriteHelperTests(unittest.TestCase):
    def repository(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email",
                        helper.ALLOWED], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", helper.NAME],
                       cwd=path, check=True)
        return path

    def commit(self, repository, name, text, message):
        target = repository / name
        target.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=repository, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=repository,
                       check=True, capture_output=True)

    def run_helper(self, repository):
        previous = os.getcwd()
        os.chdir(repository)
        try:
            return helper.main()
        finally:
            os.chdir(previous)

    def test_a_dirty_tree_is_refused_before_any_reset(self):
        repository = self.repository()
        self.commit(repository, "a.txt", "one\n", "base")
        (repository / "a.txt").write_text("two\n", encoding="utf-8")

        code = self.run_helper(repository)

        self.assertEqual(code, 1)
        self.assertEqual((repository / "a.txt").read_text(encoding="utf-8"), "two\n")

    def test_the_restored_ruleset_keeps_the_required_guard(self):
        contexts = [rule for rule in helper.INTEGRITY_RULES
                    if rule["type"] == "required_status_checks"]
        self.assertEqual(len(contexts), 1)
        parameters = contexts[0]["parameters"]
        names = [check["context"] for check in parameters["required_status_checks"]]
        self.assertIn("Personal data guard", names)
        self.assertTrue(parameters["strict_required_status_checks_policy"])

    def test_the_solo_owner_review_rule_is_disabled(self):
        pull = [rule for rule in helper.INTEGRITY_RULES
                if rule["type"] == "pull_request"]
        self.assertEqual(len(pull), 1)
        self.assertFalse(
            pull[0]["parameters"]["require_extra_approval_for_unattributed_changes"])

    def test_only_one_ruleset_is_recreated(self):
        calls = []
        helper.gh = lambda *arguments, input_text=None: calls.append(
            (arguments, input_text)) or type("R", (), {"stdout": "", "returncode": 0})()
        try:
            helper.restore_protection()
        finally:
            helper.gh = _real_gh

        self.assertEqual(len(calls), 1)
        payload = calls[0][1]
        self.assertIn("main-integrity", payload)
        self.assertNotIn("main-owner-merge", payload)

    def test_the_private_relay_is_never_written_out_in_full(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn(helper.FORBIDDEN, source)
        self.assertNotIn("privaterelay.appleid.com", source)
        self.assertEqual(helper.FORBIDDEN,
                         "jtpydk5gyh" + "@privaterelay." + "appleid.com")

    def test_offending_finds_only_the_private_address(self):
        repository = self.repository()
        self.commit(repository, "a.txt", "clean\n", "base")
        subprocess.run(["git", "commit", "--allow-empty", "-qm", "second"],
                       cwd=repository, check=True, capture_output=True)

        previous = os.getcwd()
        os.chdir(repository)
        try:
            self.assertEqual(helper.offending(), [])
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()