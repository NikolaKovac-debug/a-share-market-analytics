import numpy as np
import pandas as pd


def add_rolling_zscore(
    df: pd.DataFrame,
    value_col: str,
    window: int = 20,
    min_periods: int = 10,
) -> pd.DataFrame:
    result = df.copy()
    mean_col = f"{value_col}_ma{window}"
    std_col = f"{value_col}_std{window}"
    z_col = f"{value_col}_z{window}"

    result[mean_col] = result[value_col].rolling(window=window, min_periods=min_periods).mean()
    result[std_col] = result[value_col].rolling(window=window, min_periods=min_periods).std()
    result[z_col] = (result[value_col] - result[mean_col]) / result[std_col]
    return result


def estimate_ar1_half_life(series: pd.Series) -> dict:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 30:
        return {
            "phi": np.nan,
            "half_life": np.nan,
            "interpretation": "样本不足，无法稳定估计半衰期。",
        }

    y = clean.iloc[1:].to_numpy()
    x = clean.iloc[:-1].to_numpy()
    x = x - x.mean()
    y = y - y.mean()
    denominator = float(np.dot(x, x))
    if denominator == 0:
        phi = np.nan
    else:
        phi = float(np.dot(x, y) / denominator)

    if pd.isna(phi) or phi <= 0 or phi >= 1:
        half_life = np.nan
        interpretation = "未观察到稳定的均值回复结构。"
    else:
        half_life = float(-np.log(2) / np.log(phi))
        interpretation = f"估计半衰期约为 {half_life:.1f} 个交易日。"

    return {
        "phi": phi,
        "half_life": half_life,
        "interpretation": interpretation,
    }


def classify_zscore(z_value: float | None) -> str:
    if pd.isna(z_value):
        return "样本不足"
    if z_value >= 2:
        return "显著高于滚动均值"
    if z_value >= 1:
        return "温和高于滚动均值"
    if z_value <= -2:
        return "显著低于滚动均值"
    if z_value <= -1:
        return "温和低于滚动均值"
    return "接近滚动均值"

