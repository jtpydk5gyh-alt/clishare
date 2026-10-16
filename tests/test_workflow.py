import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Major versions that run on a runtime GitHub has retired. Node 20 reached end
# of life in April 2026 and GitHub removed it in the summer of 2026, forcing
# every job to warn until the workflow itself moves.
RETIRED = {
    "actions/checkout": {"1", "2", "3", "4"},
    "actions/setup-python": {"1", "2", "3", "4", "5"},
}


class WorkflowActionTests(unittest.TestCase):
    def setUp(self):
        self.body = WORKFLOW.read_text(encoding="utf-8")

    def used(self):
        return dict(re.findall(r"uses:\s*(actions/[\w-]+)@v(\d+)", self.body))

    def test_the_workflow_exists_and_uses_the_known_actions(self):
        self.assertTrue(WORKFLOW.is_file())
        self.assertEqual(set(self.used()), {"actions/checkout", "actions/setup-python"})

    def test_no_action_runs_on_a_retired_runtime(self):
        for action, major in self.used().items():
            with self.subTest(action=action):
                self.assertNotIn(major, RETIRED[action],
                                 f"{action}@{major} usa un runtime retirado")

    def test_every_action_is_pinned_to_a_major_version(self):
        for reference in re.findall(r"uses:\s*([\w./-]+)@(\S+)", self.body):
            with self.subTest(reference=reference[0]):
                self.assertRegex(reference[1], r"^v\d+$",
                                 "una accion sin fijar podria cambiar de comportamiento")

    def test_the_guard_is_required_by_name_and_the_matrix_is_intact(self):
        self.assertIn("Personal data guard", self.body)
        self.assertIn("python scripts/guard_secrets.py --all", self.body)
        self.assertIn("python -m unittest discover -s tests", self.body)
        for version in ("3.11", "3.12", "3.13"):
            self.assertIn(version, self.body)


if __name__ == "__main__":
    sys.exit(unittest.main())