import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cshcli.cli import _chat_loop
from cshcli.errors import DomainError
from cshcli.knowledge import index_text, note_text, search_text
from cshcli.onboarding import run_loop


class Script:
    def __init__(self, answers):
        self.answers = list(answers)

    def __call__(self, prompt):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("README.md", "# Proyecto\n")
        self.write("src/app.py", "print('hola')\n")
        self.write("docs/plan.md", "un plan\n")
        self.write(".git/config", "[core]\n")
        self.write("src/__pycache__/app.cpython-312.pyc", "binario")
        self.write("node_modules/left-pad/index.js", "module.exports = 1\n")
        self.write("dist/cshcli-0.6.0-py3-none-any.whl", "PK\x03\x04")
        (self.root / "docs").mkdir(parents=True, exist_ok=True)
        (self.root / "docs" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    def write(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return target


class IndexTests(ProjectTests):
    def test_the_index_lists_the_files_of_the_project(self):
        text = index_text(self.root)
        self.assertIn("README.md", text)
        self.assertIn("src/app.py", text)
        self.assertIn("docs/plan.md", text)

    def test_noise_and_binaries_are_left_out(self):
        text = index_text(self.root)
        for hidden in (".git/config", "__pycache__", "node_modules", "dist/", "logo.png"):
            self.assertNotIn(hidden, text)

    def test_the_readme_comes_first(self):
        text = index_text(self.root)
        self.assertLess(text.index("README.md"), text.index("docs/plan.md"))

    def test_a_budget_cuts_the_index_and_says_how_many_are_missing(self):
        text = index_text(self.root, limit=20)
        self.assertIn("omitidos", text)
        self.assertIn("- README.md", text)
        self.assertNotIn("- src/app.py", text)

    def test_an_empty_directory_has_no_index(self):
        empty = self.root / "vacio"
        empty.mkdir()
        self.assertEqual(index_text(empty), "")

    def test_a_missing_directory_is_not_an_index(self):
        with self.assertRaises(DomainError) as caught:
            index_text(self.root / "no-existe")
        self.assertEqual(caught.exception.code, "workspace_missing")

    def test_a_link_directory_is_not_followed(self):
        outside = Path(self.temp.name).parent / "cshcli-fuera"
        outside.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secreto.txt").write_text("secreto\n", encoding="utf-8", newline="\n")
        link = self.root / "enlazado"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            self.skipTest("symbolic links are not available here")
        text = index_text(self.root)
        self.assertNotIn("secreto.txt", text)


class NoteTests(ProjectTests):
    def test_a_file_becomes_a_quoted_block(self):
        text = note_text(self.root, "src/app.py")
        self.assertIn("Habla con la persona", text)
        self.assertIn("src/app.py", text)
        self.assertEqual(text.count("```"), 2)
        self.assertIn("print('hola')", text)

    def test_a_huge_file_is_cut(self):
        self.write("grande.txt", "a" * 5000)
        text = note_text(self.root, "grande.txt", limit=200)
        self.assertLessEqual(len(text), 200)

    def test_a_missing_file_is_reported(self):
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "no/existe.py")
        self.assertEqual(caught.exception.code, "file_not_found")

    def test_a_binary_file_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "docs/logo.png")
        self.assertEqual(caught.exception.code, "not_text")

    def test_a_directory_is_not_a_note(self):
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "src")
        self.assertEqual(caught.exception.code, "file_not_found")

    def test_escaping_the_project_is_refused(self):
        for candidate in ("../fuera.txt", "/etc/hosts", "src/../../fuera.txt", ".git/config"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(DomainError) as caught:
                    note_text(self.root, candidate)
                self.assertEqual(caught.exception.code, "path_rejected")

    def test_a_link_pointing_outside_is_refused(self):
        outside = Path(self.temp.name).parent / "cshcli-secreto.txt"
        outside.write_text("secreto\n", encoding="utf-8", newline="\n")
        self.addCleanup(outside.unlink)
        try:
            os.symlink(outside, self.root / "escape.txt")
        except OSError:
            self.skipTest("symbolic links are not available here")
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "escape.txt")
        self.assertEqual(caught.exception.code, "path_rejected")

    def test_a_junction_pointing_outside_is_refused(self):
        if os.name != "nt":
            self.skipTest("junctions are a Windows concept")
        outside = Path(self.temp.name).parent / "cshcli-fuera-dir"
        outside.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secreto.txt").write_text("secreto\n", encoding="utf-8", newline="\n")
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.root / "j"), str(outside)],
                                capture_output=True, text=True)
        if result.returncode:
            self.skipTest("this environment does not allow creating junctions")
        with self.assertRaises(DomainError) as caught:
            note_text(self.root, "j/secreto.txt")
        self.assertEqual(caught.exception.code, "path_rejected")


class ChatNoteTests(unittest.TestCase):
    def setUp(self):
        self.seen = []

    def ask(self, provider, model, prompt, history):
        self.seen.append(prompt)
        return "respuesta"

    def test_ver_injects_the_file_instead_of_the_command(self):
        run_loop("openai", "m", self.ask, reader=Script(["/ver docs/plan.md", "/salir"]),
                 out=io.StringIO().write, note=lambda path: "```\nun plan\n```")
        self.assertEqual(self.seen, ["```\nun plan\n```"])

    def test_ver_reports_a_missing_file_and_keeps_the_loop(self):
        out = io.StringIO()

        def note(path):
            raise DomainError(404, "file_not_found", "Ese archivo no existe.")

        run_loop("openai", "m", self.ask, reader=Script(["/ver no.py", "hola", "/salir"]),
                 out=out.write, note=note)
        self.assertIn("file_not_found", out.getvalue())
        self.assertEqual(self.seen, ["hola"])

    def test_ver_without_a_path_asks_for_one(self):
        out = io.StringIO()
        run_loop("openai", "m", self.ask, reader=Script(["/ver", "/salir"]),
                 out=out.write, note=lambda path: "x")
        self.assertEqual(self.seen, [])
        self.assertIn("ruta", out.getvalue())

    def test_ver_without_the_capability_is_refused_instead_of_sent(self):
        out = io.StringIO()
        run_loop("openai", "m", self.ask, reader=Script(["/ver a.txt", "/salir"]),
                 out=out.write)
        self.assertEqual(self.seen, [])
        self.assertIn("/ver", out.getvalue())

    def test_the_block_enters_the_conversation_like_a_question(self):
        run_loop("openai", "m", self.ask, reader=Script(["/ver a.txt", "y que hace?", "/salir"]),
                 out=io.StringIO().write, note=lambda path: "```\ncontenido\n```")
        self.assertEqual(self.seen[0], "```\ncontenido\n```")
        self.assertEqual(self.seen[1], "y que hace?")


class SearchTests(ProjectTests):
    def test_a_hit_names_the_file_and_the_line(self):
        self.write("src/app.py", "uno\ndos\ndef run():\n    return 3\n")
        text = search_text(self.root, "def run")
        self.assertIn("src/app.py", text)
        self.assertIn("src/app.py:3: def run():", text)
        self.assertIn("coincidencia", text)

    def test_the_match_is_counted_with_its_line_number(self):
        self.write("src/app.py", "uno\ndos\ndef run():\n    return 3\n")
        text = search_text(self.root, "return 3")
        self.assertIn("src/app.py:4:", text)

    def test_it_does_not_distinguish_case(self):
        self.write("src/app.py", "class Runner:\n")
        self.assertIn("src/app.py", search_text(self.root, "runner"))
        self.assertIn("src/app.py", search_text(self.root, "RUNNER"))

    def test_hits_in_several_files_are_all_reported(self):
        self.write("src/app.py", "runner\n")
        self.write("docs/plan.md", "el runner\n")
        text = search_text(self.root, "runner")
        self.assertIn("src/app.py", text)
        self.assertIn("docs/plan.md", text)

    def test_nothing_found_is_an_empty_answer_not_a_guess(self):
        self.assertEqual(search_text(self.root, "ausente"), "")

    def test_an_empty_query_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            search_text(self.root, "   ")
        self.assertEqual(caught.exception.code, "empty_query")

    def test_noise_and_binaries_are_never_searched(self):
        self.write(".git/config", "[runner]\n")
        self.write("src/__pycache__/app.pyc", "runner\n")
        (self.root / "docs" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00runner")
        text = search_text(self.root, "runner")
        self.assertNotIn(".git/config", text)
        self.assertNotIn("app.pyc", text)
        self.assertNotIn("logo.png", text)

    def test_the_answer_is_capped(self):
        self.write("grande.txt", "runner\n" * 500)
        text = search_text(self.root, "runner", limit=300)
        self.assertLessEqual(len(text), 300)

    def test_a_crowded_project_says_how_many_more_there_are(self):
        for index in range(12):
            self.write(f"mucho{index}.txt", "runner\n")
        text = search_text(self.root, "runner", matches=5)
        self.assertEqual(text.count("- mucho"), 5)
        self.assertIn("7", text)

    def test_a_folder_that_cannot_be_read_is_reported(self):
        with self.assertRaises(DomainError) as caught:
            search_text(self.root / "no-existe", "runner")
        self.assertEqual(caught.exception.code, "workspace_missing")

    def test_a_link_pointing_outside_is_never_read(self):
        outside = Path(self.temp.name).parent / "cshcli-secreto.txt"
        outside.write_text("runner\n", encoding="utf-8", newline="\n")
        self.addCleanup(outside.unlink)
        try:
            os.symlink(outside, self.root / "escape.txt")
        except OSError:
            self.skipTest("symbolic links are not available here")
        self.assertEqual(search_text(self.root, "runner"), "")


class ChatSearchTests(unittest.TestCase):
    def setUp(self):
        self.seen = []

    def ask(self, provider, model, prompt, history):
        self.seen.append(prompt)
        return "r"

    def test_buscar_puts_the_hits_in_the_conversation(self):
        run_loop("openai", "m", self.ask, reader=Script(["/buscar run", "/salir"]),
                 out=io.StringIO().write, search=lambda query: "- src/app.py:3: def run():")
        self.assertEqual(self.seen, ["- src/app.py:3: def run():"])

    def test_nothing_found_is_reported_without_asking_the_provider(self):
        out = io.StringIO()
        code = run_loop("openai", "m", self.ask, reader=Script(["/buscar nada", "/salir"]),
                        out=out.write, search=lambda query: "")
        self.assertEqual(code, 0)
        self.assertEqual(self.seen, [])
        self.assertIn("nada", out.getvalue())

    def test_buscar_without_a_query_asks_for_one(self):
        out = io.StringIO()
        run_loop("openai", "m", self.ask, reader=Script(["/buscar", "/salir"]),
                 out=out.write, search=lambda query: "x")
        self.assertEqual(self.seen, [])
        self.assertIn("texto", out.getvalue())

    def test_buscar_without_the_capability_is_refused_instead_of_sent(self):
        out = io.StringIO()
        run_loop("openai", "m", self.ask, reader=Script(["/buscar run", "/salir"]),
                 out=out.write)
        self.assertEqual(self.seen, [])
        self.assertIn("/buscar", out.getvalue())

    def test_a_refused_search_keeps_the_loop(self):
        out = io.StringIO()

        def search(query):
            raise DomainError(400, "workspace_missing", "No se puede leer esta carpeta.")

        run_loop("openai", "m", self.ask, reader=Script(["/buscar x", "hola", "/salir"]),
                 out=out.write, search=search)
        self.assertIn("workspace_missing", out.getvalue())
        self.assertEqual(self.seen, ["hola"])


class ChatWiringTests(unittest.TestCase):
    MEMORY = {"items": [{"key": "estilo", "content": "PEP8"}]}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text("# Aqui\n", encoding="utf-8", newline="\n")
        self.session = SimpleNamespace(name="ana", project="p1", project_name="demo",
                                       provider="openai", model="m",
                                       remember=lambda **fields: None)
        self.args = SimpleNamespace(provider=None, model=None, prompt=None)

    def test_the_first_question_carries_the_index_of_this_folder(self):
        client = SimpleNamespace(request=mock.Mock(return_value=self.MEMORY))
        with mock.patch("cshcli.cli.run_loop") as loop, \
                mock.patch.object(Path, "cwd", return_value=self.root):
            _chat_loop(client, self.session, self.args)
        context = loop.call_args.kwargs["context"]
        self.assertIn("Contexto compartido del proyecto 'demo'", context)
        self.assertIn("- estilo: PEP8", context)
        self.assertIn("README.md", context)
        self.assertIsNotNone(loop.call_args.kwargs["note"])

    def test_a_folder_that_cannot_be_read_does_not_break_the_chat(self):
        client = SimpleNamespace(request=mock.Mock(return_value=self.MEMORY))
        with mock.patch("cshcli.cli.run_loop") as loop, \
                mock.patch("cshcli.cli.index_text",
                           side_effect=DomainError(400, "workspace_missing", "no")):
            _chat_loop(client, self.session, self.args)
        self.assertIn("Contexto compartido", loop.call_args.kwargs["context"])


if __name__ == "__main__":
    unittest.main()