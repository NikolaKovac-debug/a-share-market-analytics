import pandas as pd


def _rolling_zscore(series: pd.Series, window: int = 20, min_periods: int = 10) -> pd.Series:
    mean = series.rolling(window=window, min_periods=min_periods).mean()
    std = series.rolling(window=window, min_periods=min_periods).std()
    return (series - mean) / std


def _consecutive_down(series: pd.Series) -> pd.Series:
    values = []
    count = 0
    for value in series.fillna(0):
        if value < 0:
            count += 1
        else:
            count = 0
        values.append(count)
    return pd.Series(values, index=series.index)


def build_stock_risk_features(market_df: pd.DataFrame) -> pd.DataFrame:
    df = market_df.copy().sort_values(["ts_code", "trade_date"])
    grouped = df.groupby("ts_code", group_keys=False)

    df["return_vol_20d"] = grouped["pct_chg"].rolling(20, min_periods=10).std().reset_index(level=0, drop=True)
    df["return_zscore_20d"] = grouped["pct_chg"].apply(_rolling_zscore).reset_index(level=0, drop=True)
    df["turnover_zscore_20d"] = grouped["amount_100m"].apply(_rolling_zscore).reset_index(level=0, drop=True)
    df["amplitude_zscore_20d"] = grouped["amplitude"].apply(_rolling_zscore).reset_index(level=0, drop=True)
    df["rolling_high_20d"] = grouped["close"].rolling(20, min_periods=10).max().reset_index(level=0, drop=True)
    df["drawdown_20d"] = (df["close"] / df["rolling_high_20d"] - 1) * 100
    df["consecutive_down_days"] = grouped["pct_chg"].apply(_consecutive_down).reset_index(level=0, drop=True)

    df["abnormal_return_flag"] = df["return_zscore_20d"].abs() >= 2
    df["abnormal_turnover_flag"] = df["turnover_zscore_20d"] >= 2
    df["high_volatility_flag"] = df["return_vol_20d"] >= df["return_vol_20d"].quantile(0.9)
    df["deep_drawdown_flag"] = df["drawdown_20d"] <= -20
    df["high_risk_flag"] = (
        df["abnormal_return_flag"]
        | df["abnormal_turnover_flag"]
        | df["high_volatility_flag"]
        | df["deep_drawdown_flag"]
    )
    df["risk_trigger_count"] = (
        df[
            [
                "abnormal_return_flag",
                "abnormal_turnover_flag",
                "high_volatility_flag",
                "deep_drawdown_flag",
            ]
        ]
        .fillna(False)
        .sum(axis=1)
    )
    df["risk_level"] = df.apply(_classify_risk_level, axis=1)
    return df


def _classify_risk_level(row) -> str:
    if row.get("risk_trigger_count", 0) >= 3:
        return "高风险"
    if row.get("drawdown_20d", 0) <= -30:
        return "高风险"
    if abs(row.get("return_zscore_20d", 0)) >= 3:
        return "高风险"
    if row.get("risk_trigger_count", 0) >= 2:
        return "警示"
    if bool(row.get("high_risk_flag", False)):
        return "观察"
    return "正常"
