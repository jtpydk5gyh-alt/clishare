import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from cshcli.errors import DomainError
from cshcli.store import Store
from cshcli.usage import BudgetPolicy, Usage


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.ana = self.store.register_user("ana")
        self.luis = self.store.register_user("luis")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.usage = Usage(self.store)

    def record(self, **keywords):
        arguments = {"provider": "openai", "model": "a-model"}
        arguments.update(keywords)
        return self.usage.record(self.project["id"], self.ana["id"], **arguments)

    def test_a_priced_call_is_recorded_with_currency_and_date(self):
        record = self.record(cost="0.0123", currency="EUR", price_as_of="2026-10-15",
                             input_tokens=100, output_tokens=50, unit="1k_tokens")
        self.assertEqual(record["cost"], "0.0123")
        self.assertEqual(record["currency"], "EUR")
        self.assertEqual(record["price_as_of"], "2026-10-15")
        self.assertEqual(record["unknown_fields"], [])

    def test_an_unpriced_call_stays_null_and_says_so(self):
        record = self.record(provider="minimax", model=None)
        self.assertIsNone(record["cost"])
        self.assertIsNone(record["currency"])
        self.assertIsNone(record["input_tokens"])
        self.assertIsNone(record["output_tokens"])
        self.assertIn("cost", record["unknown_fields"])
        self.assertIn("input_tokens", record["unknown_fields"])

    def test_a_cost_without_a_currency_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.record(cost="0.5", price_as_of="2026-10-15")
        self.assertEqual(caught.exception.code, "cost_without_currency")

    def test_a_cost_without_the_price_date_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            self.record(cost="0.5", currency="EUR")
        self.assertEqual(caught.exception.code, "cost_without_price_date")

    def test_money_keeps_its_precision(self):
        record = self.record(cost="0.1", currency="EUR", price_as_of="2026-10-15")
        self.assertEqual(record["cost"], "0.1")
        self.assertNotEqual(Decimal(record["cost"]), Decimal("0.1") + Decimal("0.2"))

    def test_an_undated_or_unreal_price_is_refused(self):
        for currency, amount in (("eur", "1"), ("EURO", "1"), ("E", "1"), (42, "1"), ("", "1")):
            with self.subTest(currency=currency):
                with self.assertRaises(DomainError):
                    self.record(cost="1", currency=currency, price_as_of="2026-10-15")

    def test_a_negative_or_unusable_amount_is_refused(self):
        for amount in ("-1", "abc", "", None if False else "NaN", float("inf"), True, [1]):
            with self.subTest(amount=amount):
                with self.assertRaises(DomainError):
                    self.record(cost=amount, currency="EUR", price_as_of="2026-10-15")

    def test_a_negative_token_count_is_refused(self):
        for value in (-1, "10", True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(DomainError):
                    self.record(input_tokens=value)

    def test_the_total_excludes_unknown_costs_and_counts_them(self):
        self.record(cost="1.00", currency="EUR", price_as_of="2026-10-15")
        self.record(cost="0.50", currency="EUR", price_as_of="2026-10-15")
        self.record(provider="minimax")
        total = self.usage.total(self.project["id"], self.ana["id"], "EUR")
        self.assertEqual(total["known_total"], "1.50")
        self.assertEqual(total["records"], 3)
        self.assertEqual(total["records_with_unknown_cost"], 1)

    def test_a_cost_in_another_currency_is_left_out(self):
        self.record(cost="1.00", currency="EUR", price_as_of="2026-10-15")
        self.record(cost="9.00", currency="USD", price_as_of="2026-10-15")
        total = self.usage.total(self.project["id"], self.ana["id"], "EUR")
        self.assertEqual(total["known_total"], "1.00")
        self.assertEqual(total["records"], 1)

    def test_an_unpriced_call_stays_visible_to_a_budget(self):
        """An unknown cost has to be counted as unknown, not dropped."""
        self.record(cost="1.00", currency="EUR", price_as_of="2026-10-15")
        self.record(provider="minimax")
        total = self.usage.total(self.project["id"], self.ana["id"], "EUR")
        self.assertEqual(total["records"], 2)
        self.assertEqual(total["known_total"], "1.00")
        self.assertEqual(total["records_with_unknown_cost"], 1)

    def test_a_subscription_without_a_published_price_stays_unknown(self):
        record = self.record(provider="claude-code", input_tokens=1000, output_tokens=200)
        self.assertIsNone(record["cost"])
        self.assertIn("cost", record["unknown_fields"])
        self.assertEqual(self.usage.total(self.project["id"], self.ana["id"], "EUR")
                         ["records_with_unknown_cost"], 1)

    def test_correlation_is_stored_and_carries_no_prompt(self):
        record = self.record(cost="0.10", currency="EUR", price_as_of="2026-10-15",
                             request_id="req-1", task_id="task-1", lease_id="lease-1",
                             fence=9)
        self.assertEqual(record["correlation"]["request_id"], "req-1")
        self.assertEqual(record["correlation"]["fence"], 9)
        self.assertNotIn("prompt", str(record).lower())

    def test_the_event_carries_no_prompt_or_key(self):
        self.record(cost="0.10", currency="EUR", price_as_of="2026-10-15",
                    request_id="req-2")
        with self.store._connection() as connection:
            rows = connection.execute("SELECT kind, data FROM events").fetchall()
        rendered = " ".join(row["kind"] + row["data"] for row in rows)
        self.assertIn("usage.recorded", rendered)
        for banned in ("prompt", "sk-", "Bearer", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertNotIn(banned, rendered)

    def test_a_non_member_cannot_record(self):
        with self.assertRaises(DomainError):
            self.usage.record(self.project["id"], self.luis["id"], "openai")

    def test_the_export_states_that_retention_is_unconfigured(self):
        self.record(cost="0.10", currency="EUR", price_as_of="2026-10-15")
        export = self.usage.export(self.project["id"], self.ana["id"])
        self.assertEqual(export["count"], 1)
        self.assertIn("not configured", export["retention"])

    def test_the_export_limit_is_bounded(self):
        for limit in (0, -1, 10001, True, "10"):
            with self.subTest(limit=limit):
                with self.assertRaises(DomainError):
                    self.usage.export(self.project["id"], self.ana["id"], limit)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "c.sqlite3")
        self.ana = self.store.register_user("ana")
        self.luis = self.store.register_user("luis")
        self.project = self.store.create_project(self.ana["id"], "demo")
        self.usage = Usage(self.store)
        self.policy = BudgetPolicy(self.store)

    def reserve(self, run_id):
        self.policy.authorize_run(self.ana["id"], self.project["id"], estimated_cost="0.01")
        generation = self.store.authorization_generation(self.ana["id"], self.project["id"])
        from cshcli.policy import Policy
        Policy(self.store).reserve_run(self.ana["id"], self.project["id"], run_id,
                                       generation, {})

    def test_eleven_agents_against_a_limit_of_ten(self):
        self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "100", max_agents=10)
        results = []
        for index in range(11):
            try:
                results.append(self.policy.authorize_run(
                    self.ana["id"], self.project["id"], estimated_cost="0.01"))
                self.reserve(f"run-{index}")
            except DomainError as error:
                results.append(error.code)
        self.assertEqual(sum(1 for item in results if isinstance(item, dict)), 10)
        self.assertEqual(results[-1], "agent_limit_reached")

    def test_an_exhausted_budget_refuses(self):
        self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "0.10", max_agents=4)
        self.usage.record(self.project["id"], self.ana["id"], "openai",
                          cost="0.10", currency="EUR", price_as_of="2026-10-15")
        with self.assertRaises(DomainError) as caught:
            self.policy.authorize_run(self.ana["id"], self.project["id"], estimated_cost="0.01")
        self.assertEqual(caught.exception.code, "budget_exceeded")

    def test_no_budget_authorises_without_guessing(self):
        result = self.policy.authorize_run(self.ana["id"], self.project["id"])
        self.assertTrue(result["authorised"])
        self.assertEqual(result["reason"], "no_budget")
        self.assertIsNone(result["spent"])

    def test_a_budget_without_an_estimate_refuses_rather_than_assuming_zero(self):
        self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "10", max_agents=2)
        with self.assertRaises(DomainError) as caught:
            self.policy.authorize_run(self.ana["id"], self.project["id"])
        self.assertEqual(caught.exception.code, "estimate_required")

    def test_an_unpriced_call_blocks_the_budget_comparison(self):
        self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "10", max_agents=2)
        self.usage.record(self.project["id"], self.ana["id"], "claude-code", input_tokens=900)
        with self.assertRaises(DomainError) as caught:
            self.policy.authorize_run(self.ana["id"], self.project["id"], estimated_cost="0.01")
        self.assertEqual(caught.exception.code, "usage_incomplete")

    def test_the_remaining_amount_is_exact(self):
        self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "1.00", max_agents=5)
        self.usage.record(self.project["id"], self.ana["id"], "openai",
                          cost="0.10", currency="EUR", price_as_of="2026-10-15")
        result = self.policy.authorize_run(self.ana["id"], self.project["id"],
                                           estimated_cost="0.05")
        self.assertEqual(result["remaining"], "0.85")
        self.assertEqual(result["spent"], "0.10")

    def test_only_the_owner_sets_a_budget(self):
        invite = self.store.create_invite(self.ana["id"], self.project["id"], "member")
        self.store.accept_invite(self.luis["id"], invite["token"])
        with self.assertRaises(DomainError):
            self.policy.set_budget(self.luis["id"], self.project["id"], "EUR", "5", max_agents=1)

    def test_a_budget_needs_a_positive_agent_ceiling(self):
        for agents in (0, -1, True, "3", 1.5):
            with self.subTest(agents=agents):
                with self.assertRaises(DomainError):
                    self.policy.set_budget(self.ana["id"], self.project["id"], "EUR", "1",
                                           max_agents=agents)

    def test_an_unknown_budget_is_refused_on_read(self):
        with self.assertRaises(DomainError) as caught:
            self.policy.get(self.project["id"], self.ana["id"], "EUR")
        self.assertEqual(caught.exception.code, "budget_not_found")


if __name__ == "__main__":
    unittest.main()