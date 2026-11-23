import tempfile
import unittest
from pathlib import Path

from investment_agent.analysis import analyze_prices, load_close_prices


class AnalyzePricesTests(unittest.TestCase):
    def test_calculates_period_return_and_trend(self):
        result = analyze_prices([10.0, 12.0, 14.0], window=2)

        self.assertAlmostEqual(result["period_return_pct"], 40.0)
        self.assertEqual(result["moving_average"], 13.0)
        self.assertEqual(result["trend"], "above")

    def test_abstains_when_there_are_too_few_prices_for_window(self):
        result = analyze_prices([10.0, 11.0], window=3)

        self.assertIsNone(result["moving_average"])
        self.assertEqual(result["trend"], "insufficient_data")

    def test_rejects_non_positive_price(self):
        with self.assertRaisesRegex(ValueError, "positivos"):
            analyze_prices([10.0, 0.0])

    def test_loads_prices_from_valid_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "prices.csv"
            csv_path.write_text(
                "date,close\n2025-01-01,10.5\n2025-01-02,11\n",
                encoding="utf-8",
            )

            self.assertEqual(load_close_prices(csv_path), [10.5, 11.0])

    def test_rejects_dates_that_are_not_ascending(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "prices.csv"
            csv_path.write_text(
                "date,close\n2025-01-02,11\n2025-01-01,10.5\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "orden ascendente"):
                load_close_prices(csv_path)


if __name__ == "__main__":
    unittest.main()
