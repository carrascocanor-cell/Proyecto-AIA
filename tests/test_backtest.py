import hashlib
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from investment_agent.backtest import BacktestConfig, run_backtest
from investment_agent.price_history import PriceBar, load_price_history_with_hash


ZERO_COSTS = BacktestConfig(
    initial_capital=Decimal("1000"),
    commission_bps=Decimal("0"),
    slippage_bps=Decimal("0"),
)


def _bars(closes: list[str]) -> list[PriceBar]:
    first_day = date(2025, 1, 1)
    return [
        PriceBar(first_day + timedelta(days=index), Decimal(close))
        for index, close in enumerate(closes)
    ]


def _trade_path() -> list[PriceBar]:
    return _bars(["100"] * 19 + ["120", "110", "120", "80", "70"])


class BacktestTests(unittest.TestCase):
    def test_signal_executes_next_close_without_looking_ahead(self):
        report = run_backtest(_trade_path(), ZERO_COSTS)
        executions = report.full_period.strategy.executions

        self.assertEqual([execution.side for execution in executions], ["buy", "sell"])
        self.assertEqual(executions[0].signal_date, date(2025, 1, 20))
        self.assertEqual(executions[0].date, date(2025, 1, 21))
        self.assertEqual(executions[0].reference_price, Decimal("110"))

    def test_future_close_changes_do_not_rewrite_prior_execution(self):
        original = _trade_path()
        changed_future = list(original)
        changed_future[21:] = [
            PriceBar(original[21].date, Decimal("500")),
            PriceBar(original[22].date, Decimal("600")),
            PriceBar(original[23].date, Decimal("700")),
        ]

        original_result = run_backtest(original, ZERO_COSTS).full_period.strategy
        changed_result = run_backtest(changed_future, ZERO_COSTS).full_period.strategy

        self.assertEqual(original_result.executions[0], changed_result.executions[0])

    def test_repeated_long_signal_does_not_duplicate_entries(self):
        bars = _bars(["100"] * 19 + ["120", "110", "105"])
        result = run_backtest(bars, ZERO_COSTS).full_period.strategy

        self.assertEqual([execution.side for execution in result.executions], ["buy"])

    def test_last_signal_is_not_executed_without_a_following_bar(self):
        bars = _bars(["100"] * 19 + ["120"])
        report = run_backtest(bars, ZERO_COSTS)

        self.assertEqual(report.full_period.strategy.executions, ())
        self.assertIsNone(report.common_operational_period)

    def test_equity_return_and_maximum_drawdown_are_known(self):
        result = run_backtest(_trade_path(), ZERO_COSTS).full_period.strategy

        self.assertEqual(result.final_equity, Decimal("700") / Decimal("110") * 100)
        self.assertAlmostEqual(float(result.return_pct), -36.3636363636, places=8)
        self.assertAlmostEqual(float(result.max_drawdown_pct), 41.6666666667, places=8)
        self.assertEqual(result.completed_round_trips, 1)
        self.assertEqual(len(result.executions), 2)

    def test_buy_respects_cash_and_balances_never_become_negative(self):
        config = BacktestConfig(
            initial_capital=Decimal("1000"),
            commission_bps=Decimal("100"),
            slippage_bps=Decimal("100"),
        )
        result = run_backtest(_trade_path(), config).full_period.strategy

        self.assertGreaterEqual(result.final_cash, Decimal("0"))
        self.assertGreaterEqual(result.final_btc, Decimal("0"))
        self.assertGreaterEqual(result.total_commission, Decimal("0"))
        self.assertGreaterEqual(result.total_slippage, Decimal("0"))
        self.assertTrue(
            all(
                point.cash >= 0 and point.btc >= 0 and point.equity >= 0
                for point in result.equity_curve
            )
        )
        entry = result.executions[0]
        self.assertLessEqual(
            entry.btc_quantity * entry.execution_price + entry.commission,
            config.initial_capital,
        )

    def test_costs_apply_to_both_strategies(self):
        config = BacktestConfig(
            initial_capital=Decimal("1000"),
            commission_bps=Decimal("100"),
            slippage_bps=Decimal("50"),
        )
        report = run_backtest(_trade_path(), config)

        self.assertGreater(report.full_period.strategy.total_commission, Decimal("0"))
        self.assertGreater(report.full_period.strategy.total_slippage, Decimal("0"))
        self.assertGreater(
            report.full_period.buy_and_hold.total_commission, Decimal("0")
        )
        self.assertGreater(report.full_period.buy_and_hold.total_slippage, Decimal("0"))

    def test_full_and_common_comparisons_use_matching_dates_and_capital(self):
        report = run_backtest(_trade_path(), ZERO_COSTS)
        full = report.full_period
        common = report.common_operational_period

        self.assertIsNotNone(common)
        self.assertEqual(full.strategy.start_date, full.buy_and_hold.start_date)
        self.assertEqual(full.strategy.end_date, full.buy_and_hold.end_date)
        self.assertEqual(
            full.strategy.initial_capital, full.buy_and_hold.initial_capital
        )
        self.assertEqual(common.strategy.start_date, common.buy_and_hold.start_date)
        self.assertEqual(common.strategy.end_date, common.buy_and_hold.end_date)
        self.assertEqual(
            common.strategy.initial_capital, common.buy_and_hold.initial_capital
        )
        self.assertEqual(common.strategy.start_date, date(2025, 1, 21))

    def test_buy_and_hold_has_known_full_period_return(self):
        result = run_backtest(_trade_path(), ZERO_COSTS).full_period.buy_and_hold

        self.assertEqual(result.final_equity, Decimal("700"))
        self.assertEqual(result.return_pct, Decimal("-30.0"))
        self.assertAlmostEqual(float(result.max_drawdown_pct), 41.6666666667, places=8)

    def test_open_position_has_separate_hypothetical_liquidation_value(self):
        config = BacktestConfig(
            initial_capital=Decimal("1000"),
            commission_bps=Decimal("100"),
            slippage_bps=Decimal("50"),
        )
        bars = _bars(["100"] * 19 + ["120", "110", "115"])
        result = run_backtest(bars, config).full_period.strategy

        expected_sell_price = bars[-1].close * Decimal("0.995")
        expected_notional = result.final_btc * expected_sell_price
        expected_commission = expected_notional * Decimal("0.01")
        expected_liquidation = (
            result.final_cash + expected_notional - expected_commission
        )
        self.assertTrue(result.open_position)
        self.assertEqual(
            result.final_market_value,
            result.final_cash + result.final_btc * bars[-1].close,
        )
        self.assertEqual(result.final_liquidation_value, expected_liquidation)
        self.assertEqual(result.liquidation_commission, expected_commission)
        self.assertLess(result.final_liquidation_value, result.final_market_value)
        self.assertEqual(len(result.executions), 1)

    def test_flat_position_has_no_hypothetical_liquidation_cost(self):
        result = run_backtest(_trade_path(), ZERO_COSTS).full_period.strategy

        self.assertFalse(result.open_position)
        self.assertEqual(result.final_liquidation_value, result.final_market_value)
        self.assertEqual(result.liquidation_commission, Decimal("0"))
        self.assertEqual(result.liquidation_slippage, Decimal("0"))

    def test_report_contains_dates_observation_count_and_csv_hash(self):
        content = b"date,close\n2025-01-01,100\n"
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "prices.csv"
            csv_path.write_bytes(content)
            bars, digest = load_price_history_with_hash(csv_path)

        report = run_backtest(bars, ZERO_COSTS, csv_sha256=digest)

        self.assertEqual(report.initial_date, date(2025, 1, 1))
        self.assertEqual(report.final_date, date(2025, 1, 1))
        self.assertEqual(report.observations, 1)
        self.assertEqual(report.csv_sha256, hashlib.sha256(content).hexdigest())

    def test_rejects_missing_daily_dates(self):
        bars = _bars(["100"] * 21)
        bars[5] = PriceBar(bars[5].date + timedelta(days=1), bars[5].close)

        with self.assertRaisesRegex(ValueError, "días ausentes"):
            run_backtest(bars, ZERO_COSTS)


if __name__ == "__main__":
    unittest.main()
