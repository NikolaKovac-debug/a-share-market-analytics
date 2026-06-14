import numpy as np
import pandas as pd


def clamp(value, lower=0, upper=100):
    if pd.isna(value):
        return float("nan")
    return max(lower, min(upper, float(value)))


def z_to_score(z_value, neutral=50, scale=15):
    if pd.isna(z_value):
        return neutral
    return clamp(neutral + float(z_value) * scale)


def percentile_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() < 5 or numeric.nunique(dropna=True) <= 1:
        return pd.Series(50.0, index=series.index)
    return numeric.rank(pct=True) * 100


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


def classify_market_regime(score, risk_ratio):
    if pd.isna(score):
        return "样本不足"
    if pd.isna(risk_ratio):
        risk_ratio = 0.2
    if risk_ratio >= 0.35 and score >= 60:
        return "过热高波动"
    if risk_ratio >= 0.35 and score >= 45:
        return "高风险分化"
    if risk_ratio >= 0.35:
        return "风险释放"
    if score >= 80:
        return "过热扩张"
    if score >= 65:
        return "Risk-on 偏强"
    if score >= 55:
        return "偏暖轮动"
    if score >= 45:
        return "结构分化"
    if score >= 35:
        return "偏弱震荡"
    return "Risk-off 收缩"


def regime_interpretation(regime):
    mapping = {
        "过热扩张": "市场温度处于高位，成交和宽度共同抬升，需要同时观察持续性与过热风险。",
        "Risk-on 偏强": "风险偏好偏强，上涨扩散或成交活跃度较好，适合观察强势行业能否延续。",
        "偏暖轮动": "市场略偏暖，但尚未进入单边扩张，行业轮动和结构性机会更重要。",
        "结构分化": "市场处于中性区间，没有明确单边状态，行业轮动和个股分化是主要观察对象。",
        "偏弱震荡": "市场温度偏低但未进入明显风险释放，适合观察成交萎缩和弱势行业扩散。",
        "Risk-off 收缩": "市场宽度和成交活跃度偏弱，风险偏好处于收缩区间。",
        "过热高波动": "赚钱效应较强但风险样本偏多，可能存在交易拥挤或短期过热。",
        "高风险分化": "风险样本占比较高，但市场温度未明显转弱，说明内部波动和结构分歧较强。",
        "风险释放": "风险股票占比较高且市场温度不足，适合重点监控回撤与流动性压力。",
        "样本不足": "当前滚动窗口不足，暂不做稳定状态判断。",
    }
    return mapping.get(regime, "市场状态需要结合成交、宽度和风险指标共同观察。")


def add_market_score_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["limit_up_intensity"] = result["limit_up_count"] / result["stock_count"].replace(0, pd.NA)
    result["risk_ratio"] = pd.to_numeric(result["risk_ratio"], errors="coerce").fillna(0.2)

    result["turnover_score"] = percentile_score(result["turnover_100m"])
    result["return_score"] = percentile_score(result["avg_return"])
    result["breadth_score"] = percentile_score(result["up_ratio"])
    result["limit_up_score"] = percentile_score(result["limit_up_intensity"])
    result["risk_control_score"] = 100 - percentile_score(result["risk_ratio"])

    result["market_heat_score"] = (
        0.25 * result["turnover_score"]
        + 0.25 * result["breadth_score"]
        + 0.20 * result["return_score"]
        + 0.15 * result["limit_up_score"]
        + 0.15 * result["risk_control_score"]
    ).clip(0, 100)
    return result


def build_market_score_detail(trend_row, risk_ratio):
    if "turnover_score" in trend_row:
        turnover_score = trend_row.get("turnover_score", float("nan"))
        return_score = trend_row.get("return_score", float("nan"))
        breadth_score = trend_row.get("breadth_score", float("nan"))
        limit_up_score = trend_row.get("limit_up_score", float("nan"))
        risk_control_score = trend_row.get("risk_control_score", float("nan"))
        explanation_suffix = "基于当前样本期历史分位数"
    else:
        turnover_score = z_to_score(trend_row.get("turnover_100m_z20", float("nan")))
        return_score = z_to_score(trend_row.get("avg_return_z20", float("nan")))
        breadth_score = z_to_score(trend_row.get("up_ratio_z20", float("nan")))
        limit_up_score = clamp(trend_row.get("limit_up_count", 0) / max(trend_row.get("stock_count", 1), 1) * 1000)
        if pd.isna(risk_ratio):
            risk_ratio = 0.2
        risk_control_score = 100 - clamp(risk_ratio * 100)
        explanation_suffix = "基于20日z-score映射"
    components = [
        {"指标": "成交活跃度", "权重": 0.25, "分项得分": turnover_score, "解释": f"成交额强弱，{explanation_suffix}"},
        {"指标": "市场宽度", "权重": 0.25, "分项得分": breadth_score, "解释": f"上涨占比强弱，{explanation_suffix}"},
        {"指标": "收益强度", "权重": 0.20, "分项得分": return_score, "解释": f"等权平均涨跌幅强弱，{explanation_suffix}"},
        {"指标": "涨停热度", "权重": 0.15, "分项得分": limit_up_score, "解释": "涨停代理占比在样本期中的历史位置"},
        {"指标": "风险控制", "权重": 0.15, "分项得分": risk_control_score, "解释": "风险样本占比越高，该项得分越低"},
    ]
    score = sum(item["权重"] * item["分项得分"] for item in components)
    return clamp(score), components


def describe_industry_signal(row):
    crowding = row.get("crowding_z20", float("nan"))
    avg_return_value = row.get("avg_return", float("nan"))
    up_ratio_value = row.get("up_ratio", float("nan"))
    if pd.notna(crowding) and crowding >= 2 and avg_return_value > 0:
        return "高拥挤强势"
    if pd.notna(crowding) and crowding >= 2 and avg_return_value <= 0:
        return "放量分歧"
    if avg_return_value > 1 and up_ratio_value >= 0.6:
        return "扩散上涨"
    if avg_return_value < -1 and up_ratio_value <= 0.4:
        return "弱势扩散"
    if pd.notna(crowding) and crowding <= -1:
        return "成交低位"
    return "中性观察"


def build_industry_signal_frame(base_df: pd.DataFrame, current_df: pd.DataFrame) -> pd.DataFrame:
    history = (
        base_df.groupby(["trade_date", "industry_label"], as_index=False)
        .agg(
            stock_count=("ts_code", "count"),
            turnover_100m=("amount_100m", "sum"),
            avg_return=("pct_chg", "mean"),
            up_ratio=("is_up", "mean"),
            net_flow_100m=("net_mf_amount_100m", "sum"),
        )
        .sort_values(["industry_label", "trade_date"])
    )
    if history.empty:
        return pd.DataFrame()

    grouped = history.groupby("industry_label", group_keys=False)
    history["turnover_ma20"] = grouped["turnover_100m"].rolling(20, min_periods=5).mean().reset_index(level=0, drop=True)
    history["turnover_std20"] = grouped["turnover_100m"].rolling(20, min_periods=5).std().reset_index(level=0, drop=True)
    history["crowding_z20"] = (history["turnover_100m"] - history["turnover_ma20"]) / history["turnover_std20"]
    history["return_ma20"] = grouped["avg_return"].rolling(20, min_periods=5).mean().reset_index(level=0, drop=True)
    history["relative_return_20d"] = history["avg_return"] - history["return_ma20"]

    current_date = current_df["trade_date"].dt.normalize().max()
    signal_df = history[history["trade_date"].dt.normalize() == current_date].copy()
    if signal_df.empty:
        return signal_df
    signal_df["signal_label"] = signal_df.apply(describe_industry_signal, axis=1)
    signal_df["crowding_score"] = signal_df["crowding_z20"].apply(lambda value: z_to_score(value))
    return signal_df.sort_values(["crowding_z20", "turnover_100m"], ascending=[False, False])


def build_risk_reason(row):
    reasons = []
    if bool(row.get("abnormal_return_flag", False)):
        reasons.append(f"涨跌幅偏离20日均值，z={row.get('return_zscore_20d', float('nan')):.2f}")
    if bool(row.get("abnormal_turnover_flag", False)):
        reasons.append(f"成交额显著放大，z={row.get('turnover_zscore_20d', float('nan')):.2f}")
    if bool(row.get("high_volatility_flag", False)):
        reasons.append(f"20日波动率较高，vol={row.get('return_vol_20d', float('nan')):.2f}")
    if bool(row.get("deep_drawdown_flag", False)):
        reasons.append(f"20日回撤较深，drawdown={row.get('drawdown_20d', float('nan')):.2f}%")
    if row.get("consecutive_down_days", 0) >= 3:
        reasons.append(f"连续下跌{int(row.get('consecutive_down_days', 0))}天")
    return "；".join(reasons) if reasons else "未触发核心风控规则"


def build_market_score_backtest(trend_signal_df: pd.DataFrame, buckets: int = 5) -> pd.DataFrame:
    df = trend_signal_df.copy().sort_values("trade_date")
    if "market_heat_score" not in df.columns or len(df) < buckets:
        return pd.DataFrame()

    df["next_avg_return"] = df["avg_return"].shift(-1)
    df["next_up_ratio"] = df["up_ratio"].shift(-1)
    clean = df.dropna(subset=["market_heat_score", "next_avg_return", "next_up_ratio"]).copy()
    if len(clean) < buckets or clean["market_heat_score"].nunique() < 2:
        return pd.DataFrame()

    try:
        clean["score_bucket"] = pd.qcut(clean["market_heat_score"], q=buckets, duplicates="drop")
    except ValueError:
        return pd.DataFrame()

    result = (
        clean.groupby("score_bucket", observed=True)
        .agg(
            sample_count=("trade_date", "count"),
            score_min=("market_heat_score", "min"),
            score_max=("market_heat_score", "max"),
            avg_next_return=("next_avg_return", "mean"),
            avg_next_up_ratio=("next_up_ratio", "mean"),
        )
        .reset_index(drop=True)
    )
    result["bucket"] = [f"Q{idx + 1}" for idx in range(len(result))]
    return result[["bucket", "sample_count", "score_min", "score_max", "avg_next_return", "avg_next_up_ratio"]]
