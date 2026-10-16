import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cshcli.cli import main
from cshcli.client import Client
from cshcli.errors import DomainError
from cshcli.local import EmbeddedCoordinator, connect
from cshcli.onboarding import Keyring, run_loop, run_wizard
from cshcli.server import make_server
from cshcli.session import Session


class Script:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "coordinator.sqlite3"
        self.server = make_server(self.database, "127.0.0.1", 0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(thread.join, 5)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.session = Session(self.root / "home")
        self.keyring = Keyring(self.root / "home")
        self.client = Client(self.url)
        self.secrets = []
        self.output = io.StringIO()

    def secret(self, prompt):
        self.secret_prompts.append(prompt)
        if not self._secret_values:
            return ""
        return self._secret_values.pop(0)

    def _reader(self, answers):
        return Script(answers)

    def run_with(self, answers, secrets):
        self._secret_values = list(secrets)
        self.secret_prompts = []
        reader = self._reader(answers)
        code = run_wizard(self.client, self.session, self.keyring,
                          reader=reader, secret=self.secret, out=self.output.write)
        return code, reader

    def text(self):
        return self.output.getvalue()

    def test_the_menu_offers_a_session_and_a_shared_project(self):
        self.run_with(["1", "ana", "", "openai"], ["sk-test"])
        printed = self.text()
        self.assertIn("1) Sesión", printed)
        self.assertIn("2) Unirme o crear", printed)

    def test_a_session_creates_the_identity_project_and_key(self):
        code, _ = self.run_with(["1", "ana", "", "openai"], ["sk-test"])
        self.assertEqual(code, 0)
        self.assertEqual(self.session.name, "ana")
        self.assertTrue(self.session.token)
        self.assertEqual(self.session.project_name, "demo")
        self.assertTrue(self.session.ready())
        self.assertEqual(self.keyring.get("openai"), "sk-test")
        projects = self.client.request("GET", "/v1/projects")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "demo")

    def test_a_named_project_is_honoured(self):
        self.run_with(["1", "ana", "mi-app", "openai"], ["sk-test"])
        self.assertEqual(self.session.project_name, "mi-app")

    def test_an_unknown_menu_choice_is_asked_again(self):
        _, reader = self.run_with(["9", "1", "ana", "", "openai"], ["sk-test"])
        self.assertIn("Opciones: 1, 2.", self.text())
        self.assertTrue(self.session.ready())

    def test_creating_a_shared_project_prints_an_invite_code(self):
        code, _ = self.run_with(["2", "ana", "n", "equipo", "openai"], ["sk-test"])
        self.assertEqual(code, 0)
        printed = self.text()
        self.assertIn("Proyecto 'equipo' creado.", printed)
        self.assertIn("Para invitar a alguien, dale este código:", printed)
        self.assertEqual(self.session.project_name, "equipo")

    def test_joining_with_a_code_records_the_other_project(self):
        owner_session = Session(self.root / "owner")
        owner_ring = Keyring(self.root / "owner")
        owner = Client(self.url)
        identity = owner.request("POST", "/v1/users", {"name": "ana"})
        owner.token = identity["token"]
        owner.request("POST", "/v1/projects", {"name": "equipo"})
        projects = owner.request("GET", "/v1/projects")
        invite = owner.request(
            "POST", f"/v1/projects/{projects[0]['id']}/invites", {"role": "member"})
        self.assertTrue(owner_session.token is None)
        self.assertTrue(owner_ring.describe("openai")["configured"] is False)

        code, _ = self.run_with(["2", "luis", "s", "openai"], [invite["token"], "sk-luis"])
        self.assertEqual(code, 0)
        self.assertEqual(self.session.name, "luis")
        self.assertEqual(self.session.project_name, "equipo")
        self.assertIn("Te uniste a 'equipo' como member.", self.text())

    def test_an_existing_key_is_not_asked_again(self):
        self.keyring.set("anthropic", "sk-already")
        _, reader = self.run_with(["1", "ana", "", "openai"], ["sk-test"])
        self.assertNotIn("¿Qué proveedor usas?", "".join(reader.prompts))
        self.assertIn("Proveedor: anthropic.", self.text())
        self.assertEqual(self.session.provider, "anthropic")
        self.assertEqual(self.keyring.get("anthropic"), "sk-already")
        self.assertIsNone(self.keyring.get("openai"))

    def test_a_ready_session_does_not_ask_anything(self):
        self.run_with(["1", "ana", "equipo", "openai"], ["sk-test"])
        self.output = io.StringIO()
        reader = self._reader([])
        code = run_wizard(self.client, self.session, self.keyring,
                          reader=reader, secret=self.secret, out=self.output.write)
        self.assertEqual(code, 0)
        self.assertEqual(reader.prompts, [])
        self.assertIn("Ya estás listo: ana en 'equipo'.", self.text())

    def test_a_non_interactive_terminal_is_refused_clearly(self):
        with self.assertRaises(DomainError) as caught:
            self.run_with([], [])
        self.assertEqual(caught.exception.code, "input_required")

    def test_an_empty_key_is_asked_again(self):
        self.run_with(["1", "ana", "", "openai"], ["", "sk-real"])
        self.assertIn("La clave llegó vacía", self.text())
        self.assertEqual(self.keyring.get("openai"), "sk-real")


class EmbeddedCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_without_a_server_the_cli_runs_its_own(self):
        database = self.root / "own.sqlite3"
        client, closers = connect(None, None, database,
                                  probe_url="http://127.0.0.1:9")
        self.addCleanup(lambda: [closer.close() for closer in closers])
        health = client.request("GET", "/health")
        self.assertEqual(health["status"], "ok")

    def test_a_running_coordinator_is_preferred(self):
        database = self.root / "shared.sqlite3"
        shared = make_server(database, "127.0.0.1", 0)
        thread = threading.Thread(target=shared.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(shared.server_close)
        self.addCleanup(shared.shutdown)
        self.addCleanup(thread.join, 5)
        url = f"http://127.0.0.1:{shared.server_address[1]}"
        client, closers = connect(None, None, self.root / "unused.sqlite3", probe_url=url)
        self.assertEqual(closers, ())
        identity = client.request("POST", "/v1/users", {"name": "ana"})
        projects = Client(url, identity["token"]).request("GET", "/v1/projects")
        self.assertEqual(projects, [])
        self.assertTrue(os.path.isdir(self.root))

    def test_an_explicit_url_is_used_as_given(self):
        client, closers = connect("http://127.0.0.1:9", None)
        self.assertEqual(closers, ())
        self.assertEqual(client.url, "http://127.0.0.1:9")

    def test_two_embedded_coordinators_share_one_database(self):
        database = self.root / "shared.sqlite3"
        first, first_closers = connect(None, None, database, probe_url="http://127.0.0.1:9")
        second, second_closers = connect(None, None, database, probe_url="http://127.0.0.1:9")
        self.addCleanup(lambda: [closer.close() for closer in first_closers + second_closers])
        identity = first.request("POST", "/v1/users", {"name": "ana"})
        authed = Client(second.url, identity["token"])
        project = authed.request("POST", "/v1/projects", {"name": "equipo"})
        self.assertEqual(project["name"], "equipo")
        self.assertEqual(len(Client(first.url, identity["token"])
                             .request("GET", "/v1/projects")), 1)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Session(Path(self.temp.name))

    def test_a_fresh_session_is_not_ready(self):
        self.assertFalse(self.session.ready())
        self.assertIsNone(self.session.token)

    def test_remembering_fields_keeps_the_others(self):
        self.session.remember(name="ana", token="t")
        self.session.remember(project="p", project_name="equipo")
        self.assertEqual(self.session.name, "ana")
        self.assertEqual(self.session.token, "t")
        self.assertTrue(self.session.ready())

    def test_a_corrupt_file_reads_as_empty(self):
        self.session.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.session.name, None)
        self.assertFalse(self.session.ready())

    def test_forgetting_removes_the_file(self):
        self.session.remember(name="ana", token="t", project="p", project_name="x")
        self.assertTrue(self.session.forget())
        self.assertFalse(self.session.path.exists())
        self.assertFalse(self.session.forget())


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.seen = []

    def ask(self, provider, model, prompt):
        self.seen.append((provider, model, prompt))
        return f"respuesta a {prompt}"

    def failing(self, provider, model, prompt):
        raise DomainError(401, "api_key_missing", "Configura la clave.")

    def test_a_line_is_sent_and_the_answer_printed(self):
        code = run_loop("openai", "gpt-4o-mini", self.ask,
                        reader=Script(["hola"]), out=self.output.write)
        self.assertEqual(code, 0)
        self.assertEqual(self.seen, [("openai", "gpt-4o-mini", "hola")])
        self.assertIn("respuesta a hola", self.output.getvalue())

    def test_slash_exit_leaves_the_loop(self):
        code = run_loop("openai", "m", self.ask,
                        reader=Script(["hola", "/salir", "nunca"]), out=self.output.write)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.seen), 1, "nothing is sent after /salir")

    def test_blank_lines_are_ignored(self):
        code = run_loop("openai", "m", self.ask,
                        reader=Script(["", "   ", "hola", "/quit"]), out=self.output.write)
        self.assertEqual(code, 0)
        self.assertEqual([item[2] for item in self.seen], ["hola"])

    def test_end_of_input_leaves_without_an_answer(self):
        code = run_loop("openai", "m", self.ask,
                        reader=Script(["hola"]), out=self.output.write)
        self.assertEqual(code, 0)
        self.assertIn("respuesta a hola", self.output.getvalue())

    def test_a_provider_error_is_reported_and_the_loop_continues(self):
        code = run_loop("openai", "m", self.failing,
                        reader=Script(["uno", "dos", "/salir"]), out=self.output.write)
        self.assertEqual(code, 0)
        self.assertEqual(self.output.getvalue().count("[api_key_missing]"), 2)


class CliStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        environment = mock.patch.dict(os.environ, {
            "CSHCLI_HOME": str(self.home),
            "CSHCLI_DB": str(self.home / "coordinator.sqlite3"),
        }, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("CSHCLI_TOKEN", "CSHCLI_URL"):
            os.environ.pop(name, None)
        self.output = io.StringIO()

    def run_main(self, argv, answers, secrets):
        reader, hidden = iter(answers), iter(secrets)
        printed = []
        with mock.patch("builtins.input", lambda prompt="": (
                printed.append(prompt), next(reader))[1]), \
             mock.patch("getpass.getpass", lambda prompt="", stream=None: (
                printed.append(prompt), next(hidden))[1]), \
             mock.patch("sys.stdout", self.output):
            code = main(argv)
        return code, "".join(printed)

    def test_cshcli_with_no_arguments_opens_the_menu(self):
        code, prompts = self.run_main([], ["1", "ana", "", "openai"], ["sk-test"])
        self.assertEqual(code, 0)
        printed = self.output.getvalue()
        self.assertIn("1) Sesión", printed)
        self.assertIn("2) Unirme o crear", printed)
        self.assertIn("¿Cómo te llamas?", prompts)
        self.assertTrue((self.home / "session.json").exists())

    def test_start_without_arguments_needs_no_server_or_token(self):
        self.run_main(["start"], ["1", "ana", "equipo", "openai"], ["sk-test"])
        code, _ = self.run_main(["project", "list"], [], [])
        self.assertEqual(code, 0)
        self.assertIn('"name": "equipo"', self.output.getvalue())

    def test_a_shared_project_starts_with_no_coordinator(self):
        code, _ = self.run_main([], ["2", "ana", "n", "equipo", "openai"], ["sk-test"])
        self.assertEqual(code, 0)
        self.assertIn("Para invitar a alguien, dale este código:",
                      self.output.getvalue())

    def test_a_ready_session_opens_the_chat_instead_of_the_wizard(self):
        self.run_main(["start"], ["1", "ana", "equipo", "openai"], ["sk-test"])
        self.output = io.StringIO()
        with mock.patch("cshcli.cli.providers.chat",
                        return_value="respuesta") as chat, \
             mock.patch("builtins.input", side_effect=["hola", "/salir"]), \
             mock.patch("sys.stdout", self.output):
            code = main([])
        self.assertEqual(code, 0)
        self.assertEqual(chat.call_args[0], ("openai", None, "hola"))
        printed = self.output.getvalue()
        self.assertIn("ana · equipo · openai", printed)
        self.assertIn("respuesta", printed)
        self.assertNotIn("Elige 1 o 2", printed)

    def test_chat_with_a_prompt_stays_a_single_query(self):
        self.run_main(["start"], ["1", "ana", "equipo", "openai"], ["sk-test"])
        self.output = io.StringIO()
        with mock.patch("cshcli.cli.providers.chat", return_value="una respuesta") as chat, \
             mock.patch("builtins.input", side_effect=AssertionError("no debe leer")), \
             mock.patch("sys.stdout", self.output):
            code = main(["chat", "--model", "gpt-4o-mini", "hola"])
        self.assertEqual(code, 0)
        self.assertEqual(chat.call_args[0], ("openai", "gpt-4o-mini", "hola"))

    def test_a_non_interactive_run_reports_it_instead_of_hanging(self):
        errors = io.StringIO()
        with mock.patch("builtins.input", side_effect=EOFError), \
             mock.patch("sys.stderr", errors):
            code = main([])
        self.assertEqual(code, 1)
        self.assertIn("input_required", errors.getvalue())
        self.assertFalse((self.home / "session.json").exists())


if __name__ == "__main__":
    unittest.main()