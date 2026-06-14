import unittest

import pandas as pd

from src.risk import build_stock_risk_features


class RiskTests(unittest.TestCase):
    def test_build_stock_risk_features(self):
        df = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 30,
                "trade_date": pd.bdate_range("2024-01-01", periods=30),
                "pct_chg": list(range(30)),
                "amount_100m": list(range(1, 31)),
                "amplitude": list(range(2, 32)),
                "close": list(range(10, 40)),
            }
        )
        result = build_stock_risk_features(df)

        expected_columns = [
            "return_vol_20d",
            "return_zscore_20d",
            "turnover_zscore_20d",
            "drawdown_20d",
            "consecutive_down_days",
            "risk_trigger_count",
            "risk_level",
            "high_risk_flag",
        ]
        for column in expected_columns:
            self.assertIn(column, result.columns)

        self.assertEqual(len(result), len(df))


if __name__ == "__main__":
    unittest.main()
