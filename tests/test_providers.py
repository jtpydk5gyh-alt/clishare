import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from cshcli.errors import DomainError
from cshcli import providers


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
        with patch("cshcli.providers.shutil.which", return_value=None):
            result = providers.status()
        rows = {row["provider"]: row for row in result}
        self.assertTrue(rows["openai"]["configured"])
        self.assertFalse(rows["anthropic"]["configured"])
        self.assertFalse(rows["codex"]["installed"])
        self.assertFalse(rows["codex"]["authentication_verified"])
        self.assertIsInstance(rows["codex"]["warning"], str)
        self.assertNotIn("never-show-this-key", json.dumps(result))

    def test_login_delegates_official_flow_and_inherits_terminal(self):
        with patch("cshcli.providers.shutil.which", return_value="official-binary"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(providers.login("claude"), 0)
        self.assertEqual(run.call_args.args[0], ["official-binary", "auth", "login"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("input", run.call_args.kwargs)

    def test_missing_cli_has_actionable_safe_error(self):
        with patch("cshcli.providers.shutil.which", return_value=None):
            with self.assertRaises(DomainError) as error:
                providers.login("codex")
        self.assertEqual(error.exception.code, "cli_not_installed")

    def test_codex_uses_stdin_read_only_and_no_user_configuration(self):
        events = '\n'.join(json.dumps(event) for event in [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "Hola"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}])
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        with patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", side_effect=[
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
        with patch("cshcli.providers.shutil.which", return_value="official-claude"), \
                patch("cshcli.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 0, "Hola", "")]) as run:
            self.assertEqual(providers.chat("claude-code", None, "Pregunta"), "Hola")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--tools") + 1], "")
        self.assertEqual(arguments[arguments.index("--disallowedTools") + 1], "mcp__*")
        self.assertIn("--safe-mode", arguments)

    def test_cli_missing_safety_flags_is_not_executed(self):
        with patch("cshcli.providers.shutil.which", return_value="old-cli"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "--model", "")) as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "cli_version_unsupported")
        self.assertEqual(run.call_count, 1)

    def test_failed_cli_never_returns_stderr_or_partial_output(self):
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        with patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 1, "private stdout", "private stderr")]):
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "provider_cli_failed")
        self.assertNotIn("private", str(error.exception))

    def test_gemini_cli_chat_refuses_unenforced_edit_guarantee(self):
        with patch("cshcli.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("gemini-cli", None, "Pregunta")
        self.assertEqual(error.exception.code, "text_mode_unavailable")
        run.assert_not_called()

    def test_capabilities_for_known_api_provider_with_key_and_model(self):
        os.environ["OPENAI_API_KEY"] = "personal-openai-secret"
        result = providers.capabilities("openai", "api", "gpt-test")
        self.assertTrue(result["configured"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["text"])
        self.assertFalse(result["tools_mediable"])
        self.assertIsNone(result["sandbox"])
        self.assertTrue(result["streaming"])
        for field in ("context_limit", "output_limit", "usage_available", "price_available"):
            self.assertEqual(result[field], "unknown")
        self.assertFalse(result["native_login"])
        self.assertEqual(result["requires_flags"], [])
        self.assertEqual(result["endpoint_hint"], "https://api.openai.com/v1/responses")
        self.assertNotIn("personal-openai-secret", json.dumps(result))

    def test_capabilities_for_known_api_provider_without_key(self):
        result = providers.capabilities("anthropic", "api", "claude-test")
        self.assertFalse(result["configured"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["endpoint_hint"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(result["requires_flags"], [])

    def test_capabilities_for_known_api_provider_with_key_but_no_model(self):
        os.environ["GEMINI_API_KEY"] = "personal-google-secret"
        for model in (None, "", "   "):
            with self.subTest(model=model):
                result = providers.capabilities("google", "api", model)
                self.assertTrue(result["configured"])
                self.assertFalse(result["verified"])
                self.assertEqual(result["endpoint_hint"], "https://generativelanguage.googleapis.com/v1beta/models")

    def test_capabilities_for_unknown_provider_returns_unknown(self):
        os.environ["OPENAI_API_KEY"] = "personal-openai-secret"
        with patch("cshcli.providers.shutil.which", return_value="official-binary"), \
                patch("cshcli.providers.subprocess.run") as run:
            result = providers.capabilities("not-a-provider", "api", "model")
        self.assertFalse(result["configured"])
        self.assertFalse(result["verified"])
        for field in providers._CAPABILITY_FIELDS:
            if field not in ("configured", "verified"):
                self.assertEqual(result[field], "unknown")
        run.assert_not_called()

    def test_capabilities_for_unknown_mode_returns_unknown(self):
        os.environ["OPENAI_API_KEY"] = "personal-openai-secret"
        with patch("cshcli.providers.shutil.which", return_value="official-binary"), \
                patch("cshcli.providers.subprocess.run") as run:
            for provider in ("openai", "codex", "claude-code", "gemini-cli"):
                with self.subTest(provider=provider):
                    result = providers.capabilities(provider, "telepathy", "model")
                    self.assertFalse(result["configured"])
                    self.assertFalse(result["verified"])
                    for field in providers._CAPABILITY_FIELDS:
                        if field not in ("configured", "verified"):
                            self.assertEqual(result[field], "unknown")
        run.assert_not_called()

    def test_capabilities_for_cli_provider_when_binary_missing(self):
        with patch("cshcli.providers.shutil.which", return_value=None), \
                patch("cshcli.providers.subprocess.run") as run:
            result = providers.capabilities("claude-code", "cli")
        self.assertFalse(result["configured"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["native_login"])
        self.assertEqual(result["requires_flags"], [])
        for field in ("text", "tools_mediable", "sandbox", "streaming", "context_limit",
                      "output_limit", "usage_available", "price_available"):
            self.assertEqual(result[field], "unknown")
        run.assert_not_called()

    def test_capabilities_for_cli_provider_when_binary_present_and_help_lists_flags(self):
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        with patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess(
                    [], 0, help_text, "")) as run:
            result = providers.capabilities("codex", "cli")
        self.assertEqual(run.call_args.args[0], ["official-codex", "exec", "--help"])
        self.assertTrue(result["configured"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["sandbox"], "read-only")
        self.assertEqual(result["requires_flags"], ["--sandbox", "--json", "--ephemeral", "--ignore-user-config"])
        self.assertNotIn("--skip-git-repo-check", result["requires_flags"])
        self.assertEqual(result["price_available"], "unknown")

    def test_capabilities_cli_sandbox_per_provider_without_inventing_it(self):
        cases = (("claude-code", "official-claude", "--tools --safe-mode --output-format --model",
                  "safe-mode", ["--tools", "--safe-mode", "--output-format"]),
                 ("gemini-cli", "official-gemini", "--model --yolo", "unknown", []),
                 ("codex", "official-codex", "--json --model", "unknown", ["--json"]))
        for provider, binary, help_text, sandbox, flags in cases:
            with self.subTest(provider=provider):
                arguments = ["official-codex", "exec", "--help"] if provider == "codex" else [binary, "--help"]
                with patch("cshcli.providers.shutil.which", return_value=binary), \
                        patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess(
                            [], 0, help_text, "")) as run:
                    result = providers.capabilities(provider, "cli")
                self.assertEqual(run.call_args.args[0], arguments)
                self.assertTrue(result["configured"])
                self.assertTrue(result["verified"])
                self.assertEqual(result["sandbox"], sandbox)
                self.assertEqual(result["requires_flags"], flags)
                self.assertTrue(result["native_login"])

    def test_capabilities_falls_back_to_unverified_when_help_fails(self):
        with patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess(
                    [], 1, "private stdout", "private stderr")):
            result = providers.capabilities("codex", "cli")
        self.assertFalse(result["verified"])
        self.assertFalse(result["configured"])
        self.assertTrue(result["native_login"])
        self.assertEqual(result["requires_flags"], [])
        self.assertEqual(result["sandbox"], "unknown")
        self.assertNotIn("private", json.dumps(result))

    def test_capabilities_does_not_invent_pricing(self):
        os.environ["OPENAI_API_KEY"] = "personal-openai-secret"
        help_text = "--sandbox read-only --json --safe-mode --output-format --model"
        with patch("cshcli.providers.shutil.which", return_value="official-binary"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess(
                    [], 0, help_text, "")):
            cases = (("openai", "api", "gpt-test"), ("anthropic", "api", None),
                     ("google", "api", "gemini-test"), ("codex", "cli", None),
                     ("claude-code", "cli", None), ("gemini-cli", "cli", None),
                     ("not-a-provider", "api", "model"), ("openai", "telepathy", "gpt-test"))
            for provider, mode, model in cases:
                with self.subTest(provider=provider, mode=mode):
                    result = providers.capabilities(provider, mode, model)
                    for field in ("price_available", "context_limit", "output_limit", "usage_available"):
                        self.assertEqual(result[field], "unknown")
                        self.assertNotIsInstance(result[field], (int, float))

    def test_redirect_does_not_forward_credentials(self):
        self.assertIsNone(providers._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.invalid"))

    def test_native_binary_required_for_windows_batch_wrappers(self):
        with patch("cshcli.providers.os.name", "nt"), \
                patch("cshcli.providers.shutil.which", return_value="C:/bin/claude.cmd"), \
                patch("cshcli.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.login("claude")
        self.assertEqual(error.exception.code, "cli_native_required")
        run.assert_not_called()

    def test_invalid_model_is_rejected_before_starting_cli(self):
        with patch("cshcli.providers.subprocess.run") as run:
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", "--dangerously-bypass-approvals-and-sandbox", "Pregunta")
        self.assertEqual(error.exception.code, "model_invalid")
        run.assert_not_called()

    def test_cli_timeout_drops_partial_output(self):
        with patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", side_effect=subprocess.TimeoutExpired(
                    ["codex"], 10, output="private partial output", stderr="private stderr")):
            with self.assertRaises(DomainError) as error:
                providers.chat("codex", None, "Pregunta")
        self.assertEqual(error.exception.code, "provider_timeout")
        self.assertNotIn("private", str(error.exception))

    def test_login_sanitizes_cshcli_and_api_secrets_preserving_official_auth(self):
        environment = {"OPENAI_API_KEY": "api-openai", "ANTHROPIC_API_KEY": "api-claude", "GEMINI_API_KEY": "api-google",
                       "CSHCLI_TOKEN": "session", "CSHCLI_INVITE_TOKEN": "invite", "CSHCLI_CUSTOM_SECRET": "other",
                       "CODEX_API_KEY": "official-codex", "CLAUDE_CODE_OAUTH_TOKEN": "official-claude", "PATH": "safe-path"}
        with patch.dict(os.environ, environment, clear=True), \
                patch("cshcli.providers.shutil.which", return_value="official-binary"), \
                patch("cshcli.providers.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            for provider in ("codex", "claude", "gemini"):
                with self.subTest(provider=provider):
                    self.assertEqual(providers.login(provider), 0)
                    child = run.call_args.kwargs["env"]
                    self.assertEqual(child, {"CODEX_API_KEY": "official-codex", "CLAUDE_CODE_OAUTH_TOKEN": "official-claude", "PATH": "safe-path"})
                    self.assertEqual(os.environ["OPENAI_API_KEY"], "api-openai")
                    self.assertEqual(os.environ["CSHCLI_TOKEN"], "session")

    def test_help_and_chat_sanitize_child_environment(self):
        environment = {"OPENAI_API_KEY": "api", "ANTHROPIC_API_KEY": "api2", "GEMINI_API_KEY": "api3",
                       "CSHCLI_TOKEN": "session", "CSHCLI_INVITE_TOKEN": "invitation", "TERM": "xterm"}
        help_text = "--sandbox read-only --json --ephemeral --ignore-user-config --model"
        events = '\n'.join(json.dumps(event) for event in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Respuesta"}},
            {"type": "turn.completed"}])
        with patch.dict(os.environ, environment, clear=True), \
                patch("cshcli.providers.shutil.which", return_value="official-codex"), \
                patch("cshcli.providers.subprocess.run", side_effect=[
                    subprocess.CompletedProcess([], 0, help_text, ""),
                    subprocess.CompletedProcess([], 0, events, "")]) as run:
            self.assertEqual(providers.chat("codex", None, "Pregunta"), "Respuesta")
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["env"], {"TERM": "xterm"})


if __name__ == "__main__":
    unittest.main()
