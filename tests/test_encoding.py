import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


def tracked_names():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                            capture_output=True, check=True)
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


class TrackedFileEncodingTests(unittest.TestCase):
    def setUp(self):
        self.names = tracked_names()

    def test_the_repository_is_not_empty(self):
        self.assertGreater(len(self.names), 0)

    def test_no_tracked_file_starts_with_a_byte_order_mark(self):
        offenders = []
        for name in self.names:
            result = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT,
                                    capture_output=True, check=False)
            if result.returncode == 0 and result.stdout.startswith(BOM):
                offenders.append(name)
        self.assertEqual(offenders, [],
                         "un BOM rompe la lectura de las herramientas que no lo esperan")

    def test_every_tracked_python_file_parses_without_stripping_a_bom(self):
        unparseable = []
        for name in self.names:
            if not name.endswith(".py"):
                continue
            source = (ROOT / name).read_text(encoding="utf-8")
            try:
                ast.parse(source)
            except SyntaxError:
                unparseable.append(name)
        self.assertEqual(unparseable, [])


if __name__ == "__main__":
    sys.exit(unittest.main())
