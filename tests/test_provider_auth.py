import tempfile
import unittest
from pathlib import Path

from cshcli.provider_auth import (REVIEWED, EligibilityError, ProviderAuth,
                                   SecureStore, redact)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RealRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SecureStore(Path(self.temp.name) / "secrets.json")
        self.auth = ProviderAuth(self.store)

    def test_nothing_is_eligible_because_nothing_was_reviewed(self):
        self.assertEqual(REVIEWED, {})
        for provider in ("openai", "anthropic", "google", "minimax",
                         "codex", "claude-code", "gemini-cli"):
            with self.subTest(provider=provider):
                report = self.auth.capabilities(provider, "chat")
                self.assertFalse(report["native_login"])
                self.assertEqual(report["reason"], "not_reviewed")
                self.assertIsNone(report["reviewed_on"])

    def test_every_provider_keeps_an_official_adapter(self):
        for provider in ("openai", "anthropic", "google", "minimax",
                         "codex", "claude-code", "gemini-cli"):
            with self.subTest(provider=provider):
                report = self.auth.capabilities(provider, "chat")
                self.assertIn("kind", report["official_adapter"])

    def test_anthropic_stays_on_a_key_or_its_official_binary(self):
        for provider in ("anthropic", "claude-code"):
            with self.subTest(provider=provider):
                self.assertFalse(self.auth.capabilities(provider, "chat")["native_login"])
                self.assertIn(self.auth.capabilities(provider, "chat")["official_adapter"]["kind"],
                              ("api_key_and_official_cli", "official_cli"))

    def test_begin_refuses_for_every_provider_today(self):
        for provider in ("openai", "anthropic", "google", "minimax"):
            with self.subTest(provider=provider):
                with self.assertRaises(EligibilityError):
                    self.auth.begin(provider, "http://127.0.0.1:8765/callback")


class ReviewedFlowTests(unittest.TestCase):
    REVIEW = {
        "openai": {
            "client_id": "registered-client-id",
            "authorize_url": "https://auth.example.invalid/authorize",
            "scope": "openid profile",
            "scopes": ["openid", "profile"],
            "modality": "subscription",
            "restrictions": ["no production credentials"],
            "reviewed_on": "2026-10-15",
        }
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.store = SecureStore(Path(self.temp.name) / "secrets.json")
        self.sent = []

        def transport(provider, payload):
            self.sent.append((provider, payload))
            return {"access_token": "secret-token-value",
                    "account_id": "acct-1",
                    "account": {"name": "ana@example.invalid", "billing": "subscription",
                                "data_destination": "the provider's own region"}}

        self.auth = ProviderAuth(self.store, reviewed=self.REVIEW,
                                 transport=transport, clock=self.clock)
        self.redirect = "http://127.0.0.1:8765/callback"

    def test_a_reviewed_provider_becomes_eligible(self):
        report = self.auth.capabilities("openai", "chat")
        self.assertTrue(report["native_login"])
        self.assertEqual(report["modality"], "subscription")
        self.assertEqual(report["reviewed_on"], "2026-10-15")
        self.assertEqual(report["scopes"], ["openid", "profile"])

    def test_an_unreviewed_provider_stays_closed_next_to_a_reviewed_one(self):
        self.assertFalse(self.auth.capabilities("anthropic", "chat")["native_login"])

    def test_begin_uses_pkce_and_a_one_use_state(self):
        began = self.auth.begin("openai", self.redirect)
        self.assertEqual(began["pkce"], "S256")
        self.assertIn("code_challenge=", began["authorization_url"])
        self.assertIn("code_challenge_method=S256", began["authorization_url"])
        self.assertGreaterEqual(len(began["state"]), 32)
        self.assertNotEqual(self.auth.begin("openai", self.redirect)["state"], began["state"])

    def test_begin_refuses_a_redirect_that_is_not_loopback(self):
        for redirect in ("https://example.invalid/callback",
                         "http://10.0.0.1/callback",
                         "http://127.0.0.1/callback#x",
                         "not a url", 42, ""):
            with self.subTest(redirect=redirect):
                with self.assertRaises(EligibilityError):
                    self.auth.begin("openai", redirect)

    def test_a_wrong_state_is_refused(self):
        self.auth.begin("openai", self.redirect)
        with self.assertRaises(EligibilityError):
            self.auth.finish("openai", "the-code", "not-the-state")

    def test_a_reused_state_is_refused(self):
        began = self.auth.begin("openai", self.redirect)
        self.auth.finish("openai", "the-code", began["state"])
        with self.assertRaises(EligibilityError):
            self.auth.finish("openai", "the-code", began["state"])

    def test_an_expired_state_is_refused(self):
        began = self.auth.begin("openai", self.redirect)
        self.clock.advance(601)
        with self.assertRaises(EligibilityError) as caught:
            self.auth.finish("openai", "the-code", began["state"])
        self.assertIn("expired", str(caught.exception))

    def test_a_state_of_another_provider_is_refused(self):
        self.auth.reviewed["minimax"] = dict(self.REVIEW["openai"])
        began = self.auth.begin("openai", self.redirect)
        with self.assertRaises(EligibilityError):
            self.auth.finish("minimax", "the-code", began["state"])

    def test_the_exchange_sends_the_verifier_and_the_exact_redirect(self):
        began = self.auth.begin("openai", self.redirect)
        self.auth.finish("openai", "the-code", began["state"])
        provider, payload = self.sent[0]
        self.assertEqual(provider, "openai")
        self.assertEqual(payload["redirect_uri"], self.redirect)
        self.assertEqual(payload["grant_type"], "authorization_code")
        self.assertTrue(payload["code_verifier"])
        self.assertEqual(len(self.sent), 1, "one exchange, no retries")

    def test_the_token_stays_local_and_the_account_is_described(self):
        began = self.auth.begin("openai", self.redirect)
        result = self.auth.finish("openai", "the-code", began["state"])
        self.assertFalse(result["coordinator_told"])
        account = self.auth.account("openai")
        self.assertEqual(account["account_name"], "ana@example.invalid")
        self.assertEqual(account["billing_modality"], "subscription")
        self.assertEqual(account["data_destination"], "the provider's own region")
        self.assertEqual(self.store.get("provider:openai"), "secret-token-value")

    def test_the_cshcli_identity_is_not_the_provider_account(self):
        began = self.auth.begin("openai", self.redirect)
        result = self.auth.finish("openai", "the-code", began["state"])
        self.assertNotIn("token", result["account"].keys())
        self.assertNotIn("access_token", str(result["account"]))

    def test_a_provider_that_returns_no_token_is_refused(self):
        def empty_transport(provider, payload):
            return {"account_id": "acct-1"}

        auth = ProviderAuth(self.store, reviewed=self.REVIEW, transport=empty_transport,
                            clock=self.clock)
        began = auth.begin("openai", self.redirect)
        with self.assertRaises(EligibilityError):
            auth.finish("openai", "the-code", began["state"])

    def test_a_missing_code_is_refused(self):
        began = self.auth.begin("openai", self.redirect)
        for code in ("", "   ", None, 42):
            with self.subTest(code=code):
                with self.assertRaises(EligibilityError):
                    self.auth.finish("openai", code, began["state"])

    def test_revoke_drops_the_token_and_the_account(self):
        began = self.auth.begin("openai", self.redirect)
        self.auth.finish("openai", "the-code", began["state"])
        self.auth.revoke("openai", "acct-1")
        self.assertIsNone(self.store.get("provider:openai"))
        self.assertIsNone(self.auth.account("openai"))

    def test_revoke_refuses_an_account_that_is_not_stored(self):
        began = self.auth.begin("openai", self.redirect)
        self.auth.finish("openai", "the-code", began["state"])
        with self.assertRaises(EligibilityError):
            self.auth.revoke("openai", "someone-else")
        self.assertEqual(self.store.get("provider:openai"), "secret-token-value")

    def test_no_secret_appears_in_any_reported_string(self):
        began = self.auth.begin("openai", self.redirect)
        result = self.auth.finish("openai", "the-code", began["state"])
        rendered = str(result) + str(self.auth.capabilities("openai", "chat"))
        self.assertNotIn("secret-token-value", rendered)
        self.assertEqual(redact("secret-token-value"), "(18 caracteres)")

    def test_a_provider_without_a_review_cannot_be_opened_by_another(self):
        with self.assertRaises(EligibilityError):
            self.auth.begin("anthropic", self.redirect)


if __name__ == "__main__":
    unittest.main()