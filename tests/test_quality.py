import unittest

import pandas as pd

from src.quality import build_quality_report


class QualityTests(unittest.TestCase):
    def test_build_quality_report(self):
        df = pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
                "name": ["平安银行", "平安银行"],
                "industry": ["银行", None],
                "market": ["主板", "主板"],
                "close": [10.0, 10.1],
                "pct_chg": [1.0, 1.1],
                "amount_100m": [2.0, 2.1],
            }
        )
        report = build_quality_report(df, "analytics_market_daily", ["ts_code", "trade_date"])

        self.assertIn("metric", report.columns)
        self.assertIn("row_count", set(report["metric"]))
        self.assertIn("industry_missing_rate", set(report["metric"]))
        duplicate_row = report[report["metric"] == "duplicate_key_count"].iloc[0]
        self.assertEqual(duplicate_row["value"], 1.0)


if __name__ == "__main__":
    unittest.main()
