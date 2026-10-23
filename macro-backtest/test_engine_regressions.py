import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import backtest as bt
import historical_validation as hv
import persist_results as pr
import runtime_acceptance as ra
import weighting_test as wt


ROOT = Path(__file__).resolve().parents[1]


class MetricRegressionTests(unittest.TestCase):
    def test_first_period_loss_is_a_drawdown(self):
        result = bt.stats([-0.20, 0.10])
        self.assertAlmostEqual(result["max_drawdown"], -0.20, places=12)

    def test_flat_prices_report_initial_allocation_fee(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28"]),
        )
        _, result, _ = bt.run(
            "FEE_FIXTURE", prices, {}, {"AAA": 1.0}, "benchmark", 500, 0, 0, ["AAA"]
        )
        self.assertAlmostEqual(result["ending_value"], 499.75, places=8)
        self.assertAlmostEqual(result["ann_return"], (1.0 - bt.FEE) ** 12 - 1.0, places=12)
        self.assertLess(result["ann_return"], 0.0)

    def test_contributions_do_not_become_investment_return(self):
        prices = pd.DataFrame(
            {"AAA": [100.0] * 4},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"]),
        )
        old_fee = bt.FEE
        bt.FEE = 0.0
        try:
            _, result, _ = bt.run(
                "FLOW_FIXTURE", prices, {}, {"AAA": 1.0}, "benchmark", 500, 100, 0, ["AAA"]
            )
        finally:
            bt.FEE = old_fee
        self.assertAlmostEqual(result["ann_return"], 0.0, places=12)
        self.assertAlmostEqual(result["ending_value"], 800.0, places=8)
        self.assertEqual(result["months"], 3)

    def test_all_scenarios_use_the_supplied_common_window(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0], "BBB": [np.nan, 50.0, 50.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
        )
        _, result, _ = bt.run(
            "COMMON_WINDOW_FIXTURE", prices, {}, {"AAA": 1.0}, "benchmark", 500, 0, 0, ["AAA"]
        )
        self.assertEqual(result["actual_start"], "2025-02-28")
        self.assertEqual(result["months"], 1)


class HistoricalAccountingTests(unittest.TestCase):
    def test_flow_adjusted_values_are_flat_with_contributions(self):
        dates = pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"])
        values = pd.Series([500.0, 600.0, 700.0], index=dates)
        flows = {dates[1]: 100.0, dates[2]: 100.0}
        result = hv.stats_from_values(values, cash_flows=flows, initial_value=500.0)
        self.assertAlmostEqual(result["ann_return"], 0.0, places=12)
        self.assertEqual(result["months"], 2)

    def test_anchor_forward_flat_prices_do_not_turn_contributions_into_return(self):
        prices = pd.DataFrame(
            {"AAA": [100.0, 100.0, 100.0, 100.0]},
            index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"]),
        )
        result = hv.run_anchor_forward(
            prices,
            {
                "anchor_date": "2025-01-31",
                "targets": {"AAA": 1.0},
                "initial_capital": 500,
                "monthly_contribution": 100,
                "fee": 0.0,
                "cash_target": 0.0,
                "refill_method": "target_gap",
            },
        )
        self.assertAlmostEqual(result["metrics"]["ann_return"], 0.0, places=12)
        self.assertAlmostEqual(result["metrics"]["ending_value"], 800.0, places=8)
        self.assertEqual(result["metrics"]["months"], 3)
        self.assertEqual(result["test_type"], "ANCHOR_FORWARD_THESIS")
        for label in [
            "test_type",
            "information_set",
            "requested_start",
            "actual_start",
            "actual_end",
            "start_reason",
            "bias_classification",
            "months",
        ]:
            self.assertIn(label, result)

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

    def test_current_partial_month_is_excluded_even_on_month_end(self):
        now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        previous_month_end = now.to_period("M").start_time - pd.Timedelta(days=1)
        prices = pd.DataFrame(
            {"AAA": [100.0, 101.0]},
            index=pd.to_datetime([previous_month_end, now]),
        )
        completed = bt._completed_monthly_last(prices)
        self.assertTrue((completed.index.to_period("M") < now.to_period("M")).all())
        self.assertEqual(len(completed), 1)


class WorkflowRegressionTests(unittest.TestCase):
    WRITERS = [
        "macro-backtest.yml",
        "macro-current-portfolio-backtest.yml",
        "macro-defense-mix-test.yml",
        "macro-dependency-cap-test.yml",
        "macro-historical-validation.yml",
        "macro-orchestration-split-test.yml",
        "macro-weighting-test.yml",
    ]

    def test_result_writer_queue_configuration_is_explicit(self):
        for name in self.WRITERS:
            text = (ROOT / ".github" / "workflows" / name).read_text()
            self.assertIn("group: macro-backtest-v08-results-writer", text, name)
            self.assertIn("queue: max", text, name)
            self.assertIn("cancel-in-progress: false", text, name)
            self.assertNotIn("cancel-in-progress: true", text, name)

    def test_result_writers_checkout_and_persist_the_selected_branch(self):
        for name in self.WRITERS:
            text = (ROOT / ".github" / "workflows" / name).read_text()
            self.assertIn("ref: ${{ github.sha }}", text, name)
            self.assertIn("macro-backtest-v08-repair", text, name)
            self.assertIn("python macro-backtest/persist_results.py", text, name)
            self.assertNotIn("ref: macro-backtest-v08", text, name)
            self.assertNotIn("HEAD:macro-backtest-v08", text, name)

    def test_result_persistence_rejects_stale_source_changes(self):
        self.assertEqual(
            pr.AUTHORIZED_BRANCHES,
            {"macro-backtest-v08", "macro-backtest-v08-repair"},
        )
        self.assertEqual(
            pr.validate_result_path("macro-backtest/results-historical-validation"),
            "macro-backtest/results-historical-validation",
        )
        for path in [
            "macro-backtest/results/output.json",
            "macro-backtest/results-weighting/summary.csv",
        ]:
            self.assertTrue(pr.is_result_artifact_path(path), path)
        for path in [
            "macro-backtest/backtest.py",
            ".github/workflows/macro-backtest.yml",
            "macro-backtest/results-escape",
        ]:
            self.assertFalse(pr.is_result_artifact_path(path), path)
        with self.assertRaisesRegex(RuntimeError, "non-result path"):
            pr.validate_result_path("macro-backtest/backtest.py")
        with self.assertRaisesRegex(RuntimeError, "unsafe result path"):
            pr.validate_result_path("../macro-backtest/results")

    def test_result_persistence_rejects_unauthorized_branch_before_git(self):
        with mock.patch.dict("os.environ", {"GITHUB_REF_NAME": "main"}, clear=False):
            with mock.patch.object(pr, "_git") as git:
                with self.assertRaisesRegex(RuntimeError, "unauthorized branch"):
                    pr.main(["macro-backtest/results", "fixture"])
                git.assert_not_called()

    def test_result_persistence_rejects_source_change_before_rebase_or_push(self):
        calls = []

        def fake_git(*args, **kwargs):
            calls.append(args)
            if args == ("rev-parse", "HEAD"):
                return subprocess.CompletedProcess(args, 0, stdout="source-sha\n")
            if args == ("diff", "--cached", "--quiet"):
                return subprocess.CompletedProcess(args, 1)
            if args == ("rev-parse", "origin/macro-backtest-v08-repair"):
                return subprocess.CompletedProcess(args, 0, stdout="remote-sha\n")
            if args[:2] == ("merge-base", "--is-ancestor"):
                return subprocess.CompletedProcess(args, 0)
            if args == ("diff", "--name-only", "source-sha..remote-sha"):
                return subprocess.CompletedProcess(
                    args, 0, stdout="macro-backtest/backtest.py\n"
                )
            return subprocess.CompletedProcess(args, 0, stdout="")

        with mock.patch.dict(
            "os.environ", {"GITHUB_REF_NAME": "macro-backtest-v08-repair"}, clear=False
        ):
            with mock.patch.object(pr, "_git", side_effect=fake_git):
                with self.assertRaisesRegex(RuntimeError, "source files changed"):
                    pr.main(["macro-backtest/results", "fixture"])

        self.assertNotIn(("rebase", "origin/macro-backtest-v08-repair"), calls)
        self.assertNotIn(("push", "origin", "HEAD:macro-backtest-v08-repair"), calls)

    def test_offline_pr_ci_checks_out_the_selected_repair_tree(self):
        text = (ROOT / ".github" / "workflows" / "macro-engine-tests.yml").read_text()
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", text)

    def test_runtime_acceptance_uses_only_synthetic_isolated_outputs(self):
        text = (ROOT / ".github" / "workflows" / "macro-writer-runtime-acceptance.yml").read_text()
        self.assertIn("queue: max", text)
        self.assertIn("max-parallel: 3", text)
        self.assertIn("$RUNNER_TEMP/macro-writer-runtime-acceptance", text)
        self.assertNotIn("results-current-portfolio", text)
        self.assertNotIn("results-historical-validation", text)

    def test_runtime_acceptance_persists_only_to_isolated_same_branch_remote(self):
        head = pr._git("rev-parse", "HEAD", capture_output=True).stdout.strip()
        with tempfile.TemporaryDirectory(prefix=".macro-runtime-test-", dir=ROOT) as temp:
            output = Path(temp) / "slot-1.json"
            record = ra.run_acceptance(1, output, head, ra.REPAIR_BRANCH)
            ra.validate_record(record, head, ra.REPAIR_BRANCH)
            self.assertTrue(record["synthetic"])
            self.assertFalse(record["contains_financial_results"])
            self.assertEqual(
                record["persistence"]["changed_paths"],
                ["macro-backtest/results-runtime-acceptance/slot-1.json"],
            )

    def test_orchestration_dependency_paths_are_complete(self):
        text = (ROOT / ".github" / "workflows" / "macro-orchestration-split-test.yml").read_text()
        for dependency in ["backtest.py", "dependency_cap_test.py", "satellite_weight_test.py"]:
            self.assertIn(dependency, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
