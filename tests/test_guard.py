import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "guard_secrets.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_secrets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_guard()


class GuardTests(unittest.TestCase):
    def write(self, name, text):
        path = Path(self.temp.name) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def repository(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", guard.ALLOWED_EMAIL],
                       cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "Trankideal"],
                       cwd=path, check=True)
        return path

    def run_guard(self, repository, *arguments):
        environment = dict(os.environ)
        environment["GIT_CONFIG_GLOBAL"] = str(repository / "gitconfig-global")
        environment["GIT_CONFIG_SYSTEM"] = str(repository / "gitconfig-system")
        (repository / "gitconfig-global").write_text("", encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                              cwd=repository, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=environment)

    def test_the_noreply_address_is_the_only_allowed_email(self):
        self.assertEqual(guard.ALLOWED_EMAIL, "jtpydk5gyh-alt@users.noreply.github.com")

    def test_a_personal_email_is_flagged(self):
        name = self.write("doc.md", "contact: ana.lopez@correo-real.net\n")
        findings, _ = guard.scan([name], "")
        self.assertTrue(any("correo" in label for _, _, label, _ in findings))

    def test_the_private_relay_address_is_flagged_explicitly(self):
        name = self.write("doc.md", "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        findings, _ = guard.scan([name], "")
        self.assertTrue(any("privada" in label for _, _, label, _ in findings))

    def test_the_noreply_address_is_not_flagged(self):
        name = self.write("doc.md", f"owner: {guard.ALLOWED_EMAIL}\n")
        self.assertEqual(guard.scan([name], ""), ([], []))

    def test_reserved_example_domains_are_allowed(self):
        name = self.write("doc.md", "a@example.com b@example.invalid c@example.org d@remote.example\n")
        self.assertEqual(guard.scan([name], ""), ([], []))

    def test_system_user_paths_are_flagged(self):
        for content in ("path: C:/Users/67gang/Documents\n",
                        "path: /home/67gang/project\n",
                        "path: /Users/67gang/project\n"):
            with self.subTest(content=content):
                name = self.write("doc.md", content)
                findings, _ = guard.scan([name], "")
                self.assertTrue(any("ruta" in label for _, _, label, _ in findings))

    def test_tokens_and_private_keys_are_flagged(self):
        name = self.write("doc.md",
                          "key sk-abcdefghijklmnopqrstuvwxyz012345\ngh ghp_abcdefghijklmnopqrstuvwxyz012345\n"
                          "-----BEGIN RSA PRIVATE KEY-----\n")
        labels = [label for _, _, label, _ in guard.scan([name], "")[0]]
        self.assertTrue(any("token" in label for label in labels))
        self.assertTrue(any("clave privada" in label for label in labels))

    def test_a_clean_file_produces_no_findings(self):
        name = self.write("doc.md", "# Title\n\nNormal prose with no personal data.\n")
        self.assertEqual(guard.scan([name], ""), ([], []))

    def test_the_guard_exempts_only_its_own_test_file(self):
        self.assertEqual(guard.SELF_EXEMPT, {"tests/test_guard.py"})
        exempt = self.write(os.path.join("tests", "test_guard.py"),
                            "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        self.assertEqual(guard.scan([exempt], ""), ([], []))
        other = self.write(os.path.join("tests", "test_other.py"),
                           "contact: jtpydk5gyh@privaterelay.appleid.com\n")
        self.assertTrue(guard.scan([other], "")[0])

    def test_the_installer_refuses_to_overwrite_an_existing_hook(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install_hooks.py"
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            (repository / "scripts").mkdir()
            (repository / "scripts" / "guard_secrets.py").write_text("", encoding="utf-8")
            hooks = repository / ".git" / "hooks"
            hooks.mkdir(exist_ok=True)
            existing = hooks / "pre-commit"
            existing.write_text("#!/bin/sh\necho mine\n", encoding="utf-8", newline="\n")

            result = subprocess.run([sys.executable, str(installer)],
                                    cwd=repository, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 1)
            self.assertIn("ya existe un hook", result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")

    def test_the_installer_refuses_when_the_guard_is_missing(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install_hooks.py"
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            result = subprocess.run([sys.executable, str(installer)],
                                    cwd=repository, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 1)
            self.assertIn("no existe el guard", result.stderr)
            self.assertFalse((repository / ".git" / "hooks" / "pre-commit").exists())

    def test_the_installer_creates_the_hook_when_there_is_none(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install_hooks.py"
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            (repository / "scripts").mkdir()
            guard = repository / "scripts" / "guard_secrets.py"
            guard.write_text("", encoding="utf-8")
            result = subprocess.run([sys.executable, str(installer)],
                                    cwd=repository, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            hook = repository / ".git" / "hooks" / "pre-commit"
            self.assertTrue(hook.is_file())
            body = hook.read_text(encoding="utf-8")
            self.assertTrue(body.startswith("#!/bin/sh"))
            self.assertIn("guard_secrets.py", body)

    def test_the_report_never_prints_the_detected_value(self):
        secret = "sk-" + "q" * 24
        name = self.write("doc.md", "key " + secret + "\n")
        findings, _ = guard.scan([name], "")
        self.assertTrue(findings)
        for _, _, _, sample in findings:
            self.assertNotIn("qqqq", guard.redact_sample(sample))
            self.assertNotEqual(guard.redact_sample(sample), sample)

    def test_the_redacted_sample_keeps_the_shape_not_the_content(self):
        redacted = guard.redact_sample("sk-qqqqqqqqqqqqqqqqqqqqqqqqqq")
        self.assertNotIn("qqqq", redacted)
        self.assertIn("caracteres", redacted)
        self.assertRegex(redacted, r"\d+ caracteres")

    def test_the_redacted_sample_masks_short_values_completely(self):
        redacted = guard.redact_sample("ab@cd")
        self.assertNotIn("ab", redacted.replace("caracteres", ""))

    def test_main_output_contains_no_fragment_of_the_secret(self):
        secret = "sk-" + "z" * 24
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            target = repository / "doc.md"
            target.write_text("key " + secret + "\n", encoding="utf-8")
            subprocess.run(["git", "add", "doc.md"], cwd=repository, check=True)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "doc.md"],
                cwd=repository, capture_output=True, text=True, encoding="utf-8",
                errors="replace")
            output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("zzzz", output)
        self.assertNotIn(secret, output)
        self.assertIn("doc.md:1", output)

    def test_identity_findings_rejects_a_wrong_email(self):
        with mock.patch.object(guard.subprocess, "run") as run:
            run.side_effect = [
                type("R", (), {"stdout": "ana@gmail.com\n", "returncode": 0})(),
                type("R", (), {"stdout": "ana@gmail.com\n", "returncode": 0})(),
            ]
            problems = guard.identity_findings()
        self.assertEqual(len(problems), 2)
        self.assertIn(guard.ALLOWED_EMAIL, problems[0])

    def test_identity_findings_accepts_the_noreply_email(self):
        with mock.patch.object(guard.subprocess, "run") as run:
            run.side_effect = [
                type("R", (), {"stdout": guard.ALLOWED_EMAIL + "\n", "returncode": 0})(),
                type("R", (), {"stdout": guard.ALLOWED_EMAIL + "\n", "returncode": 0})(),
            ]
            self.assertEqual(guard.identity_findings(), [])

    def test_the_staged_index_is_read_and_not_the_working_tree(self):
        """The whole point of the guard: scan what git is about to record.

        If it read the working tree, an agent that edits a file after staging
        it would be judged on text that is never committed, while the staged
        text reaches the remote unexamined. That is the exact shape of the
        leak that reached a squash merge.
        """
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            target = repository / "doc.md"
            target.write_text("contact: ana@correo-real.net\n", encoding="utf-8")
            subprocess.run(["git", "add", "doc.md"], cwd=repository, check=True)
            target.write_text("clean text, nothing personal here\n", encoding="utf-8")

            staged = subprocess.run(["git", "show", ":doc.md"], cwd=repository,
                                    capture_output=True, text=True, check=True,
                                    encoding="utf-8")
            self.assertIn("correo-real.net", staged.stdout)

            result = self.run_guard(repository)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("doc.md:1", output)

    def test_a_clean_index_is_not_blocked_by_a_dirty_working_tree(self):
        """The opposite asymmetry: uncommitted edits must not fail the commit."""
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", guard.ALLOWED_EMAIL],
                           cwd=repository, check=True)
            target = repository / "doc.md"
            target.write_text("clean text, nothing personal here\n", encoding="utf-8")
            subprocess.run(["git", "add", "doc.md"], cwd=repository, check=True)
            target.write_text("contact: ana@correo-real.net\n", encoding="utf-8")

            result = self.run_guard(repository)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)

    def test_committed_text_builds_a_valid_git_spec(self):
        """A colon-prefixed revision must not be given a second colon.

        "::name" is rejected by git, and the rejection used to be read as
        "content unavailable", which sent the guard to the working tree.
        """
        built = []

        def capture(command, **keywords):
            built.append(command)
            return type("R", (), {"stdout": "", "returncode": 0})()

        with mock.patch.object(guard.subprocess, "run", side_effect=capture):
            guard.committed_text("doc.md", ":")
            guard.committed_text("doc.md", "HEAD")

        self.assertEqual(built[0], ["git", "show", ":doc.md"])
        self.assertEqual(built[1], ["git", "show", "HEAD:doc.md"])

    def test_the_index_is_read_from_a_real_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            target = repository / "doc.md"
            target.write_text("content\n", encoding="utf-8")
            subprocess.run(["git", "add", "doc.md"], cwd=repository, check=True)

            previous = os.getcwd()
            os.chdir(repository)
            try:
                index_text = guard.committed_text("doc.md", ":")
                head_missing = guard.committed_text("doc.md", "HEAD")
            finally:
                os.chdir(previous)

        self.assertEqual(index_text, "content\n")
        self.assertIsNone(head_missing)

    def test_an_unreadable_index_is_refused_rather_than_substituted(self):
        """Falling back to the working tree is how the guard failed open."""
        with tempfile.TemporaryDirectory() as temp:
            repository = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            target = repository / "doc.md"
            target.write_text("clean text, nothing personal here\n", encoding="utf-8")
            subprocess.run(["git", "add", "doc.md"], cwd=repository, check=True)
            target.write_text("contact: ana@correo-real.net\n", encoding="utf-8")

            real_run = subprocess.run

            def refuse_show(command, *arguments, **keywords):
                if command[:2] == ["git", "show"]:
                    return type("R", (), {"stdout": "", "returncode": 128,
                                          "stderr": "", "args": ""})()
                return real_run(command, *arguments, **keywords)

            with mock.patch.object(guard.subprocess, "run", side_effect=refuse_show):
                result = guard.main(["doc.md"])

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()