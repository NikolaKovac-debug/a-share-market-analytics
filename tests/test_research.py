import unittest

import pandas as pd

from src.research import (
    add_market_score_columns,
    add_rolling_zscore,
    build_industry_signal_frame,
    build_market_score_backtest,
    build_market_score_detail,
    classify_market_regime,
    classify_zscore,
    estimate_ar1_half_life,
)


class ResearchTests(unittest.TestCase):
    def test_add_rolling_zscore_creates_columns(self):
        df = pd.DataFrame({"value": range(30)})
        result = add_rolling_zscore(df, "value", window=20, min_periods=10)

        self.assertIn("value_ma20", result.columns)
        self.assertIn("value_std20", result.columns)
        self.assertIn("value_z20", result.columns)
        self.assertTrue(result["value_z20"].notna().any())

    def test_estimate_ar1_half_life_returns_dict(self):
        series = pd.Series([0.8**i for i in range(60)])
        result = estimate_ar1_half_life(series)

        self.assertIn("phi", result)
        self.assertIn("half_life", result)
        self.assertIn("interpretation", result)

    def test_classify_zscore(self):
        self.assertEqual(classify_zscore(2.5), "显著高于滚动均值")
        self.assertEqual(classify_zscore(0.2), "接近滚动均值")
        self.assertEqual(classify_zscore(-2.5), "显著低于滚动均值")

    def test_market_score_columns_and_detail(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.bdate_range("2024-01-01", periods=10),
                "stock_count": [100] * 10,
                "turnover_100m": range(10, 20),
                "avg_return": range(-5, 5),
                "up_ratio": [idx / 10 for idx in range(10)],
                "limit_up_count": range(10),
                "risk_ratio": [0.1] * 10,
            }
        )
        result = add_market_score_columns(df)
        self.assertIn("market_heat_score", result.columns)
        score, components = build_market_score_detail(result.iloc[-1].to_dict(), 0.1)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertEqual(len(components), 5)

    def test_classify_market_regime(self):
        self.assertEqual(classify_market_regime(85, 0.1), "过热扩张")
        self.assertEqual(classify_market_regime(50, 0.4), "高风险分化")
        self.assertEqual(classify_market_regime(30, 0.1), "Risk-off 收缩")

    def test_industry_signal_frame(self):
        rows = []
        dates = pd.bdate_range("2024-01-01", periods=25)
        for trade_date in dates:
            for industry in ["银行", "半导体"]:
                rows.append(
                    {
                        "trade_date": trade_date,
                        "industry_label": industry,
                        "ts_code": f"{industry}{trade_date.day}",
                        "amount_100m": 10 + trade_date.day,
                        "pct_chg": 1.0,
                        "is_up": True,
                        "net_mf_amount_100m": 0.1,
                    }
                )
        base_df = pd.DataFrame(rows)
        current_df = base_df[base_df["trade_date"] == dates[-1]]
        result = build_industry_signal_frame(base_df, current_df)
        self.assertFalse(result.empty)
        self.assertIn("signal_label", result.columns)

    def test_market_score_backtest(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.bdate_range("2024-01-01", periods=20),
                "market_heat_score": range(20),
                "avg_return": [value / 10 for value in range(20)],
                "up_ratio": [0.5] * 20,
            }
        )
        result = build_market_score_backtest(df)
        self.assertFalse(result.empty)
        self.assertIn("avg_next_return", result.columns)


if __name__ == "__main__":
    unittest.main()
