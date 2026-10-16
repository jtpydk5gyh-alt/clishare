import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "CHANGELOG.md", "docs")

BEFORE = 300
AFTER = 120

FORBIDDEN = (
    re.compile(r"\bsin PostgreSQL\b", re.IGNORECASE),
    re.compile(r"\bno hay PostgreSQL\b", re.IGNORECASE),
    re.compile(r"\bsin servidor\b", re.IGNORECASE),
    re.compile(r"\bno hay (?:servidor|Docker|WSL|Podman|GPG|minisign)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:Levantar|servicio remoto|aún no se ha levantado)[^.\n|]{0,70}"
               r"(?:queda pendiente|aún no se ha levantado|pendiente)"),
    re.compile(r"\bsigue bloqueado sin servidor\b", re.IGNORECASE),
)

PAST = ("no había", "no habia", "era verdad", "era cierto", "entonces",
        "cuando se escribi", "en el momento de escribirse", "dejó de ser",
        "dejo de ser", "ya no lo es", "quedó obsoleta", "quedo obsoleta",
        "actualizado", "resuelto", "como se ha resuelto")


def markdown_files():
    for name in DOCS:
        path = ROOT / name
        if path.is_file():
            yield path
        elif path.is_dir():
            for entry in sorted(path.rglob("*.md")):
                yield entry


def offenders_in(text):
    found = []
    for pattern in FORBIDDEN:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - BEFORE):match.end() + AFTER]
            if any(marker in window for marker in PAST):
                continue
            excerpt = " ".join(window.split())[:120]
            found.append(f"{excerpt}")
    return found


class StaleInfrastructureClaimsTests(unittest.TestCase):
    def test_the_documents_that_are_checked_are_the_ones_that_exist(self):
        names = {str(path.relative_to(ROOT)).replace("\\", "/")
                 for path in markdown_files()}
        self.assertIn("docs/CONTEXT.md", names)
        self.assertIn("docs/PLAN-ONLINE.md", names)

    def test_the_proven_infrastructure_is_never_declared_absent_in_the_present(self):
        offenders = []
        for path in markdown_files():
            text = path.read_text(encoding="utf-8")
            for excerpt in offenders_in(text):
                offenders.append(f"{path.relative_to(ROOT)}: {excerpt}")
        self.assertEqual(offenders, [],
                         "la infraestructura probada no puede declararse ausente en presente")

    def test_a_bare_claim_is_caught_and_the_past_tense_is_excused(self):
        self.assertTrue(offenders_in("No hay servidor en esta maquina."))
        self.assertEqual(
            offenders_in("Cuando se escribio esto no habia servidor, ni Docker, "
                         "ni WSL, ni PostgreSQL en la maquina."),
            [])


class CheckedAgainstHistoryTests(unittest.TestCase):
    def test_the_check_would_have_caught_the_claims_it_replaces(self):
        caught = 0
        for path in ("docs/CONTEXT.md", "docs/PLAN-ONLINE.md", "docs/PLAN-INFRA.md"):
            result = subprocess.run(["git", "show", f"6c930d8:{path}"],
                                    cwd=ROOT, capture_output=True, check=False)
            if result.returncode != 0:
                self.skipTest("el commit anterior no esta disponible aqui")
            caught += len(offenders_in(result.stdout.decode("utf-8", errors="replace")))
        self.assertGreaterEqual(caught, 9,
                                "si el texto viejo pasara el control, el control no sirve")


if __name__ == "__main__":
    sys.exit(unittest.main())
