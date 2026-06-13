import unittest

import pandas as pd

from src.research import add_rolling_zscore, classify_zscore, estimate_ar1_half_life


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


if __name__ == "__main__":
    unittest.main()
