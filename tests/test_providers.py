"""Provider boundaries: real request construction, synthetic network/process I/O."""

import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from clishare.errors import DomainError
from clishare import providers


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def api_reply(self, value):
        return patch.object(providers._OPENER, "open", return_value=io.BytesIO(json.dumps(value).encode()))

    def test_openai_request_uses_responses_and_extracts_only_text(self):
        os.environ["OPENAI_API_KEY"] = "personal-openai-secret"
        response = {"id": "resp_123", "object": "response", "status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": "Hola", "annotations": []}]}]}
        with self.api_reply(response) as send:
            self.assertEqual(providers.chat("openai", "gpt-test", "Explica esto"), "Hola")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer personal-openai-secret")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "gpt-test")
        self.assertEqual(body["input"], "Explica esto")
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertGreater(send.call_args.kwargs["timeout"], 0)

    def test_anthropic_request_uses_personal_header_and_messages(self):
        os.environ["ANTHROPIC_API_KEY"] = "personal-anthropic-secret"
        response = {"id": "msg_123", "type": "message", "role": "assistant", "model": "claude-test",
                    "content": [{"type": "text", "text": "Respuesta"}], "stop_reason": "end_turn",
                    "stop_sequence": None, "usage": {"input_tokens": 4, "output_tokens": 2}}
        with self.api_reply(response) as send:
            self.assertEqual(providers.chat("anthropic", "claude-test", "Pregunta"), "Respuesta")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "personal-anthropic-secret")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(json.loads(request.data)["messages"], [{"role": "user", "content": "Pregunta"}])

    def test_google_uses_key_header_never_query_string(self):
        os.environ["GEMINI_API_KEY"] = "personal-google-secret"
        response = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Bien"}]},
                                    "finishReason": "STOP", "index": 0}],
                    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
                    "modelVersion": "gemini-test", "responseId": "abc"}
        with self.api_reply(response) as send:
            self.assertEqual(providers.chat("google", "gemini-test", "Pregunta"), "Bien")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertEqual(request.get_header("X-goog-api-key"), "personal-google-secret")
        self.assertNotIn("personal-google-secret", request.full_url)

    def test_model_and_key_required_without_contacting_provider(self):
        with patch.object(providers._OPENER, "open") as send:
            for provider in ("openai", "anthropic", "google"):
                with self.subTest(provider=provider):
                    with self.assertRaises(DomainError) as error:
                        providers.chat(provider, None, "Hola")
                    self.assertEqual(error.exception.code, "model_required")
                    with self.assertRaises(DomainError) as error:
                        providers.chat(provider, "test-model", "Hola")
                    self.assertEqual(error.exception.code, "api_key_missing")
            send.assert_not_called()

    def test_http_errors_never_expose_remote_body_or_credentials(self):
        os.environ["OPENAI_API_KEY"] = "do-not-leak-this"
        remote = HTTPError("https://example.invalid/?key=do-not-leak-this", 401,
                           "secret remote reason", {}, io.BytesIO(b"private remote body"))
        with patch.object(providers._OPENER, "open", side_effect=remote):
            with self.assertRaises(DomainError) as error:
                providers.chat("openai", "test-model", "Hola")
        self.assertEqual(error.exception.code, "provider_auth_failed")
        self.assertNotIn("do-not-leak-this", str(error.exception))
        self.assertNotIn("remote", str(error.exception))

    def test_network_errors_and_timeouts_are_safe(self):
        os.environ["OPENAI_API_KEY"] = "secret"
        for failure, code in [(URLError("secret network detail"), "provider_unavailable"),
                              (TimeoutError("secret timeout detail"), "provider_timeout"),
                              (URLError(TimeoutError("secret timeout detail")), "provider_timeout")]:
            with patch.object(providers._OPENER, "open", side_effect=failure):
                with self.assertRaises(DomainError) as error:
                    providers.chat("openai", "test-model", "Hola")
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("secret", str(error.exception))

    def test_invalid_empty_and_incomplete_responses_are_not_success(self):
        os.environ["OPENAI_API_KEY"] = "secret"
        for response in ({}, [], {"status": "incomplete", "output": []},
                         {"status": "completed", "output": None},
                         {"status": "completed", "output": 12},
                         {"status": "completed", "output": [{"type": "function_call", "arguments": "secret"}]}):
            with self.api_reply(response):
                with self.assertRaises(DomainError):
                    providers.chat("openai", "test-model", "Hola")
        with patch.object(providers._OPENER, "open", return_value=io.BytesIO(b"secret invalid json")):
            with self.assertRaises(DomainError) as error:
                providers.chat("openai", "test-model", "Hola")
            self.assertNotIn("secret", str(error.exception))

    def test_successful_text_redacts_known_environment_keys(self):
        os.environ["OPENAI_API_KEY"] = "secret-key-value"
        with self.api_reply({"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "La clave secret-key-value"}]}]}):
            self.assertEqual(providers.chat("openai", "model", "Hola"), "La clave [REDACTED]")

    def test_status_exposes_only_booleans_and_public_metadata(self):
        os.environ["OPENAI_API_KEY"] = "never-show-this-key"
        with patch("clishare.providers.shutil.which", return_value=None):
            result = providers.status()
        rows = {row["provider"]: row for row in result}
        self.assertTrue(rows["openai"]["configured"])
        self.assertFalse(rows["anthropic"]["configured"])
        self.assertFalse(rows["codex"]["installed"])
        self.assertFalse(rows["codex"]["authentication_verified"])
        self.assertIsInstance(rows["codex"]["warning"], str)
        self.assertNotIn("never-show-this-key", json.dumps(result))

    def test_login_delegates_official_flow_and_inherits_terminal(self):
        with patch("clishare.providers.shutil.which", return_value="official-binary"), \
                patch("clishare.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(providers.login("claude"), 0)
        self.assertEqual(run.call_args.args[0], ["official-binary", "auth", "login"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("input", run.call_args.kwargs)

    def test_missing_cli_has_actionable_safe_error(self):
        with patch("clishare.providers.shutil.which", return_value=None):
            with self.assertRaises(DomainError) as error:
                providers.login("codex")
        self.assertEqual(error.exception.code, "cli_not_installed")

    def test_codex_uses_stdin_read_only_and_no_user_configuration(self):
        events = '\n'.join(json.dumps(event) for event in [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "Hola"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}])
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        with patch("clishare.providers.shutil.which", return_value="official-codex"), \
                patch("clishare.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 0, events, "")]) as run:
            self.assertEqual(providers.chat("codex", "model-test", "hola; $(danger)"), "Hola")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--sandbox") + 1], "read-only")
        self.assertIn("--ignore-user-config", arguments)
        self.assertEqual(arguments[-1], "-")
        self.assertNotIn("hola; $(danger)", arguments)
        self.assertEqual(run.call_args.kwargs["input"], "hola; $(danger)")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotEqual(run.call_args.kwargs["cwd"], os.getcwd())
        self.assertIn("--skip-git-repo-check", arguments)

    def test_claude_disables_builtin_mcp_tools_and_customizations(self):
        help_text = "--tools --disallowedTools --safe-mode --no-session-persistence --output-format --model"
        with patch("clishare.providers.shutil.which", return_value="official-claude"), \
                patch("clishare.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 0, "Hola", "")]) as run:
            self.assertEqual(providers.chat("claude-code", None, "Pregunta"), "Hola")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--tools") + 1], "")
        self.assertEqual(arguments[arguments.index("--disallowedTools") + 1], "mcp__*")
        self.assertIn("--safe-mode", arguments)

    def test_cli_missing_safety_flags_is_not_executed(self):
        with patch("clishare.providers.shutil.which", return_value="old-cli"), \
                patch("clishare.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "--model", "")) as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "cli_version_unsupported")
        self.assertEqual(run.call_count, 1)

    def test_failed_cli_never_returns_stderr_or_partial_output(self):
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        with patch("clishare.providers.shutil.which", return_value="official-codex"), \
                patch("clishare.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 1, "private stdout", "private stderr")]):
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "provider_cli_failed")
        self.assertNotIn("private", str(error.exception))

    def test_gemini_cli_chat_refuses_unenforced_edit_guarantee(self):
        with patch("clishare.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("gemini-cli", None, "Pregunta")
        self.assertEqual(error.exception.code, "text_mode_unavailable")
        run.assert_not_called()

    def test_redirect_does_not_forward_credentials(self):
        self.assertIsNone(providers._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.invalid"))

    def test_native_binary_required_for_windows_batch_wrappers(self):
        with patch("clishare.providers.os.name", "nt"), \
                patch("clishare.providers.shutil.which", return_value="C:/bin/claude.cmd"), \
                patch("clishare.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.login("claude")
        self.assertEqual(error.exception.code, "cli_native_required")
        run.assert_not_called()

    def test_invalid_model_is_rejected_before_starting_cli(self):
        with patch("clishare.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", "--dangerously-bypass-approvals-and-sandbox", "Pregunta")
        self.assertEqual(error.exception.code, "model_invalid")
        run.assert_not_called()

    def test_cli_timeout_drops_partial_output(self):
        with patch("clishare.providers.shutil.which", return_value="official-codex"), \
                patch("clishare.providers.subprocess.run", side_effect=subprocess.TimeoutExpired(
                    ["codex"], 10, output="private partial output", stderr="private stderr")):
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "provider_timeout")
        self.assertNotIn("private", str(error.exception))

    def test_login_sanitizes_clishare_and_api_secrets_preserving_official_auth(self):
        environment = {"OPENAI_API_KEY": "api-openai", "ANTHROPIC_API_KEY": "api-claude", "GEMINI_API_KEY": "api-google",
                       "CLISHARE_TOKEN": "session", "CLISHARE_INVITE_TOKEN": "invite", "CLISHARE_CUSTOM_SECRET": "other",
                       "CODEX_API_KEY": "official-codex", "CLAUDE_CODE_OAUTH_TOKEN": "official-claude", "PATH": "safe-path"}
        with patch.dict(os.environ, environment, clear=True), \
                patch("clishare.providers.shutil.which", return_value="official-binary"), \
                patch("clishare.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            for provider in ("codex", "claude", "gemini"):
                with self.subTest(provider=provider):
                    self.assertEqual(providers.login(provider), 0)
                    child = run.call_args.kwargs["env"]
                    self.assertEqual(child, {"CODEX_API_KEY": "official-codex", "CLAUDE_CODE_OAUTH_TOKEN": "official-claude", "PATH": "safe-path"})
                    self.assertEqual(os.environ["OPENAI_API_KEY"], "api-openai")
                    self.assertEqual(os.environ["CLISHARE_TOKEN"], "session")

    def test_help_and_chat_sanitize_child_environment(self):
        environment = {"OPENAI_API_KEY": "api", "ANTHROPIC_API_KEY": "api2", "GEMINI_API_KEY": "api3",
                       "CLISHARE_TOKEN": "session", "CLISHARE_INVITE_TOKEN": "invitation", "TERM": "xterm"}
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        events = '\n'.join(json.dumps(event) for event in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Respuesta"}},
            {"type": "turn.completed"}])
        with patch.dict(os.environ, environment, clear=True), \
                patch("clishare.providers.shutil.which", return_value="official-codex"), \
                patch("clishare.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 0, events, "")]) as run:
            self.assertEqual(providers.chat("codex", None, "Pregunta"), "Respuesta")
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"], {"TERM": "xterm"})


if __name__ == "__main__":
    unittest.main()
