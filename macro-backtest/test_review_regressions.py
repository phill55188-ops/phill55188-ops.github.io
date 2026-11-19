"""Offline regressions for capped weights, event receipts and complete months."""
import random
import sys
import types
import unittest
from unittest import mock

import pandas as pd

sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))

import brutality_test as brutality
import historical_validation as hv
import weighting_test as wt


class EventReceiptTests(unittest.TestCase):
    def test_requested_250_dollar_buy_with_100_cash_reports_partial_fill(self):
        dates = pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"])
        prices = pd.DataFrame({"AAA": 10.0}, index=dates)
        order = {"date": "2025-02-28", "type": "BUY_DOLLARS", "ticker": "AAA", "dollars": 250}
        result = hv.run_event_dated(prices, {
            "anchor_date": "2025-01-31", "initial_capital": 100,
            "fee": 0.01, "events": [order],
        })
        fill = result["events_applied"][0]
        self.assertEqual(fill["status"], "PARTIAL")
        self.assertEqual((fill["executed_dollars"], fill["unfilled_dollars"]), (100, 150))
        self.assertAlmostEqual(fill["net_share_change"], 9.9)
        self.assertAlmostEqual(result["performance"]["metrics"]["ending_value"], 99)

    def test_unfunded_buy_records_zero_execution(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
        )
        result = hv.run_event_dated(
            prices,
            {
                "anchor_date": "2025-01-31",
                "initial_capital": 100,
                "fee": 0.0,
                "initial_targets": {"AAA": 1.0},
                "cash_target": 0.0,
                "events": [
                    {"date": "2025-02-01", "type": "BUY_DOLLARS", "ticker": "AAA", "dollars": 100}
                ],
            },
        )
        event = result["events_applied"][0]
        self.assertEqual(event["status"], "NOT_EXECUTED")
        self.assertEqual(event["requested_dollars"], 100.0)
        self.assertEqual(event["executed_dollars"], 0.0)
        self.assertEqual(event["unfilled_dollars"], 100.0)

    def test_oversized_sell_records_partial_execution(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
        )
        result = hv.run_event_dated(
            prices,
            {
                "anchor_date": "2025-01-31",
                "initial_capital": 100,
                "fee": 0.0,
                "initial_targets": {"AAA": 1.0},
                "cash_target": 0.0,
                "events": [
                    {"date": "2025-02-01", "type": "SELL_DOLLARS", "ticker": "AAA", "dollars": 200}
                ],
            },
        )
        event = result["events_applied"][0]
        self.assertEqual(event["status"], "PARTIAL")
        self.assertEqual(event["requested_dollars"], 200.0)
        self.assertAlmostEqual(event["executed_dollars"], 100.0, places=8)
        self.assertAlmostEqual(event["unfilled_dollars"], 100.0, places=8)

    def test_share_buy_then_sell_preserves_executed_quantity_and_charges_fees(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
        )
        result = hv.run_event_dated(
            prices,
            {
                "anchor_date": "2025-01-31",
                "initial_capital": 101.0,
                "fee": 0.01,
                "initial_targets": {},
                "events": [
                    {"date": "2025-01-31", "type": "BUY_SHARES", "ticker": "AAA", "shares": 1.0},
                    {"date": "2025-02-28", "type": "SELL_SHARES", "ticker": "AAA", "shares": 1.0},
                ],
            },
        )
        buy, sell = result["events_applied"]
        self.assertEqual(buy["status"], "APPLIED")
        self.assertEqual(buy["executed_shares"], 1.0)
        self.assertEqual(buy["unfilled_shares"], 0.0)
        self.assertEqual(buy["fee_dollars"], 1.0)
        self.assertEqual(buy["net_cash_change"], -101.0)
        self.assertEqual(sell["status"], "APPLIED")
        self.assertEqual(sell["executed_shares"], 1.0)
        self.assertEqual(sell["unfilled_shares"], 0.0)
        self.assertEqual(sell["fee_dollars"], 1.0)
        self.assertEqual(sell["net_cash_change"], 99.0)
        self.assertAlmostEqual(result["metrics"]["ending_value"], 99.0, places=8)

    def test_share_buy_requires_cash_for_price_plus_fee(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
        )
        with self.assertRaisesRegex(RuntimeError, "insufficient cash"):
            hv.run_event_dated(
                prices,
                {
                    "anchor_date": "2025-01-31",
                    "initial_capital": 100.0,
                    "fee": 0.01,
                    "initial_targets": {},
                    "events": [
                        {
                            "date": "2025-01-31",
                            "type": "BUY_SHARES",
                            "ticker": "AAA",
                            "shares": 1.0,
                        }
                    ],
                },
            )


class IntegrityPropertyTests(unittest.TestCase):
    def test_canonical_cap_is_enforced_after_redistribution(self):
        capped = wt.capped_growth(0.10)
        growth = {ticker: capped[ticker] for ticker in wt.GROWTH}
        self.assertAlmostEqual(sum(growth.values()), 0.81, places=12)
        self.assertLessEqual(max(growth.values()), 0.10 + 1e-12)

    def test_random_feasible_caps_preserve_sum_and_bound(self):
        rng = random.Random(20261023)
        original = wt.GROWTH
        try:
            for _ in range(250):
                count = rng.randint(5, 24)
                raw = [rng.expovariate(1.0) for _ in range(count)]
                weights = [0.81 * value / sum(raw) for value in raw]
                cap = rng.uniform(0.81 / count * 1.01, min(0.25, 0.81))
                if cap * count < 0.81:
                    cap = 0.81 / count + 1e-9
                wt.GROWTH = {f"T{i}": value for i, value in enumerate(weights)}
                capped = wt.capped_growth(cap)
                growth = [capped[ticker] for ticker in wt.GROWTH]
                self.assertAlmostEqual(sum(growth), 0.81, places=9)
                self.assertLessEqual(max(growth), cap + 1e-10)
        finally:
            wt.GROWTH = original


    def test_stress_loader_filters_unfinished_month_and_keeps_friday_close(self):
        prices = pd.DataFrame({"Close": [10., 11.]},
                              index=pd.to_datetime(["2026-10-30", "2026-11-12"]))
        with mock.patch.object(brutality.yf, "download", return_value=prices, create=True), \
             mock.patch.object(brutality, "completed_session_prices",
                               side_effect=lambda raw: completed(raw, "2026-11-30")):
            monthly = brutality.load_prices([])
        self.assertEqual(monthly.index.tolist(), [pd.Timestamp("2026-10-31")])
        self.assertTrue((monthly.iloc[0] == 10.).all())

    def test_stale_ticker_at_completed_month_end_is_rejected(self):
        prices = pd.DataFrame({"A": [3., 4.], "B": [2., float("nan")]},
                              index=pd.to_datetime(["2026-10-29", "2026-10-30"]))
        with self.assertRaisesRegex(ValueError, "Missing final-session close for B"):
            completed(prices, "2026-11-05")


completed = brutality.completed_session_prices

if __name__ == "__main__":
    unittest.main()
