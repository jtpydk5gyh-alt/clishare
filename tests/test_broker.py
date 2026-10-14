import json
import os
import unittest
from unittest.mock import patch

from cshcli.errors import DomainError
from cshcli.broker import Broker

_SECRET_ENVIRONMENT = {
    "OPENAI_API_KEY": "leak-openai-9f1c",
    "ANTHROPIC_API_KEY": "leak-anthropic-3a7d",
    "GEMINI_API_KEY": "leak-gemini-5b2e",
    "CSHCLI_TOKEN": "leak-token-71a4",
    "CSHCLI_URL": "leak-url-2b90",
    "CSHCLI_CUSTOM_SECRET": "leak-custom-64de",
}
_MANIFEST = {"task_id": "task-1", "entries": [
    {"key": "project/name", "content": "CSHCLI"},
    {"key": "style/voice", "content": "Responde en español."}]}
_MANIFEST_PROMPT = "project/name\nCSHCLI\nstyle/voice\nResponde en español."


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.binary = patch("cshcli.providers.shutil.which", return_value=None)
        self.binary.start()
        self.addCleanup(self.binary.stop)
        self.calls = []
        self.broker = Broker(provider_callable=self.fake, clock=lambda: 1700000000.5)

    def fake(self, provider, model, prompt):
        self.calls.append({"provider": provider, "model": model, "prompt": prompt})
        return "Respuesta del proveedor"

    def test_generate_delegates_to_the_provider_with_the_manifest_prompt(self):
        result = self.broker.generate("run-1", "openai", "gpt-test", _MANIFEST)
        self.assertEqual(self.calls, [{"provider": "openai", "model": "gpt-test", "prompt": _MANIFEST_PROMPT}])
        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["model"], "gpt-test")
        self.assertEqual(result["text"], "Respuesta del proveedor")
        self.assertEqual(result["generated_at"], 1700000000.5)
        self.assertEqual(sorted(result), ["capabilities", "generated_at", "model", "provider", "run_id", "text"])

    def test_generate_prefers_the_explicit_prompt(self):
        result = self.broker.generate("run-1", "anthropic", "claude-test", _MANIFEST, prompt="Pregunta directa")
        self.assertEqual(self.calls, [{"provider": "anthropic", "model": "claude-test", "prompt": "Pregunta directa"}])
        self.assertEqual(result["text"], "Respuesta del proveedor")
        for prompt in (None, "", "   "):
            with self.subTest(prompt=prompt):
                self.calls.clear()
                self.broker.generate("run-1", "anthropic", "claude-test", _MANIFEST, prompt=prompt)
                self.assertEqual(self.calls[0]["prompt"], _MANIFEST_PROMPT)

    def test_generate_rejects_an_empty_provider(self):
        for provider in ("", "   ", None):
            with self.subTest(provider=provider):
                with self.assertRaises(DomainError) as error:
                    self.broker.generate("run-1", provider, None, _MANIFEST)
                self.assertEqual(error.exception.code, "invalid_provider")
                self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.calls, [])

    def test_generate_rejects_a_manifest_without_entries(self):
        for manifest in ({}, {"task_id": "task-1"}, {"entries": []}, {"entries": "project/name"}, None):
            with self.subTest(manifest=manifest):
                with self.assertRaises(DomainError) as error:
                    self.broker.generate("run-1", "openai", "gpt-test", manifest)
                self.assertEqual(error.exception.code, "invalid_manifest")
                self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.calls, [])

    def test_generate_rejects_a_provider_without_text_capability(self):
        with self.assertRaises(DomainError) as error:
            self.broker.generate("run-1", "not-a-provider", "model-test", _MANIFEST)
        self.assertEqual(error.exception.code, "invalid_provider")
        self.assertEqual(self.calls, [])

    def test_generate_uses_the_shared_provider_callable_when_no_override_is_injected(self):
        broker = Broker()
        with patch("cshcli.providers.chat", return_value="Respuesta real") as send:
            result = broker.generate("run-1", "openai", "gpt-test", _MANIFEST)
        send.assert_called_once_with("openai", "gpt-test", _MANIFEST_PROMPT)
        self.assertEqual(result["text"], "Respuesta real")
        self.assertEqual(self.calls, [])

    def test_generate_defers_configuration_errors_to_the_provider_call(self):
        result = self.broker.generate("run-1", "codex", None, _MANIFEST)
        self.assertEqual(self.calls[0]["provider"], "codex")
        self.assertFalse(result["capabilities"]["configured"])
        self.assertTrue(result["capabilities"]["native_login"])
        self.assertEqual(result["capabilities"]["text"], "unknown")

    def test_generate_result_carries_no_secret(self):
        os.environ["OPENAI_API_KEY"] = "never-show-this-key"
        os.environ["CSHCLI_TOKEN"] = "never-show-this-token"
        result = self.broker.generate("run-1", "openai", "gpt-test", _MANIFEST)
        self.assertEqual(sorted(result), ["capabilities", "generated_at", "model", "provider", "run_id", "text"])
        serialized = json.dumps(result, default=str)
        self.assertNotIn("never-show-this-key", serialized)
        self.assertNotIn("never-show-this-token", serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertNotIn("CSHCLI_TOKEN", serialized)
        self.assertNotIn("os.environ", serialized)
        Broker.assert_no_secrets({"result": serialized},
                                 ["never-show-this-key", "never-show-this-token"])

    def test_child_environment_keeps_only_run_id_scope_and_path(self):
        os.environ.update({"PATH": "safe-path", "HOME": "home", "TERM": "xterm"})
        child = self.broker.child_environment("run-1", "repo")
        self.assertEqual(child, {"CSHCLI_RUN_ID": "run-1", "CSHCLI_RUN_SCOPE": "repo", "PATH": "safe-path"})
        self.assertEqual(sorted(child), ["CSHCLI_RUN_ID", "CSHCLI_RUN_SCOPE", "PATH"])

    def test_child_environment_strips_api_keys_and_cshcli_secrets(self):
        os.environ.update(_SECRET_ENVIRONMENT)
        os.environ["PATH"] = "safe-path"
        child = self.broker.child_environment("run-1", "repo")
        self.assertEqual(child, {"CSHCLI_RUN_ID": "run-1", "CSHCLI_RUN_SCOPE": "repo", "PATH": "safe-path"})
        serialized = json.dumps(child)
        for value in _SECRET_ENVIRONMENT.values():
            self.assertNotIn(value, serialized)
        for name in _SECRET_ENVIRONMENT:
            self.assertNotIn(name, child)
            self.assertNotIn(name, serialized)

    def test_child_environment_strips_secrets_even_if_caller_passes_them(self):
        with patch.dict(os.environ, {**_SECRET_ENVIRONMENT, "PATH": "safe-path", "HOME": "home"}, clear=True):
            child = self.broker.child_environment("run-1", "repo")
            parent = dict(os.environ)
        self.assertEqual(child, {"CSHCLI_RUN_ID": "run-1", "CSHCLI_RUN_SCOPE": "repo", "PATH": "safe-path"})
        for name, value in _SECRET_ENVIRONMENT.items():
            self.assertNotIn(value, json.dumps(child))
            self.assertNotIn(value, child.get("PATH", ""))
            self.assertIn(name, parent)
        Broker.assert_no_secrets(child, list(_SECRET_ENVIRONMENT.values()))
        with patch.dict(os.environ, _SECRET_ENVIRONMENT, clear=True):
            self.assertEqual(sorted(self.broker.child_environment("run-1", "repo")),
                             ["CSHCLI_RUN_ID", "CSHCLI_RUN_SCOPE"])

    def test_assert_no_secrets_detects_a_leaked_value(self):
        environment = {"CSHCLI_RUN_ID": "run-1", "OPENAI_API_KEY": "sk-leak-openai-9f1c", "CSHCLI_RUN_SCOPE": "repo"}
        with self.assertRaises(DomainError) as error:
            Broker.assert_no_secrets(environment, ["sk-leak-openai-9f1c"])
        self.assertEqual(error.exception.code, "secret_leak")
        self.assertEqual(error.exception.status, 500)
        self.assertNotIn("sk-leak-openai-9f1c", str(error.exception))
        Broker.assert_no_secrets({"CSHCLI_RUN_ID": "run-1", "PATH": "safe-path"},
                                 ["sk-leak-openai-9f1c"])
        Broker.assert_no_secrets({"PATH": "safe-path"}, [])
        with self.assertRaises(DomainError):
            Broker.assert_no_secrets({"PATH": "prefix-sk-leak-openai-9f1c-suffix"}, ["sk-leak-openai-9f1c"])

    def test_child_environment_without_inherited_path_keeps_only_run_markers(self):
        child = self.broker.child_environment("run-2", "repo")
        self.assertEqual(child, {"CSHCLI_RUN_ID": "run-2", "CSHCLI_RUN_SCOPE": "repo"})


if __name__ == "__main__":
    unittest.main()