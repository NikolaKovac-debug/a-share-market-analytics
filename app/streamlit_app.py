from pathlib import Path
import gc
import os
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import DB_PATH
from src.research import (
    add_market_score_columns,
    add_rolling_zscore,
    build_industry_signal_frame,
    build_market_score_detail,
    build_market_score_backtest,
    build_risk_reason,
    classify_market_regime,
    classify_zscore,
    estimate_ar1_half_life,
    regime_interpretation,
)
from src.risk import build_stock_risk_features


ANALYTICS_TABLE = "analytics_market_daily"
DEMO_TABLE = "market_daily_demo"

ACCENT = "#d6a84f"
INK = "#172033"
GRID = "#e7ebf0"

COLUMN_LABELS = {
    "ts_code": "股票代码",
    "symbol": "股票简称代码",
    "name": "股票名称",
    "industry": "行业",
    "market": "板块",
    "area": "地区",
    "trade_date": "交易日期",
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "pre_close": "昨收价",
    "change": "涨跌额",
    "pct_chg": "涨跌幅",
    "vol": "成交量",
    "amount": "成交额",
    "amount_100m": "成交额_亿元",
    "turnover_100m": "成交额_亿元",
    "avg_amount_20d": "20日平均成交额",
    "std_amount_20d": "20日成交额标准差",
    "amount_zscore": "成交额z值",
    "stock_count": "股票数量",
    "avg_return": "平均涨跌幅",
    "up_ratio": "上涨占比",
    "vol_20d": "20日波动率",
    "limit_up_count": "涨停代理数",
    "turnover_zscore_20d": "成交额z值",
    "return_zscore_20d": "涨跌幅z值",
    "amplitude_zscore_20d": "振幅z值",
    "return_vol_20d": "20日波动率",
    "drawdown_20d": "20日回撤",
    "consecutive_down_days": "连续下跌天数",
    "high_risk_flag": "风险标记",
    "is_up": "是否上涨",
    "is_limit_up_proxy": "涨停代理",
    "is_limit_down_proxy": "跌停代理",
    "net_mf_amount_100m": "资金净流入_亿元",
    "net_flow_100m": "资金净流入_亿元",
}


@st.cache_resource
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def close_cached_connection():
    con = None
    try:
        con = get_connection()
        con.close()
    except Exception:
        pass
    finally:
        del con

    st.cache_resource.clear()
    gc.collect()


def table_exists(con, table_name):
    return (
        con.execute(
            """
            select count(*)
            from information_schema.tables
            where table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
        > 0
    )


def get_tushare_token():
    token = os.getenv("TUSHARE_TOKEN", "")

    try:
        secret_token = st.secrets.get("TUSHARE_TOKEN", "")
        if secret_token:
            token = secret_token
    except Exception:
        pass

    if token:
        os.environ["TUSHARE_TOKEN"] = str(token)

    return token


def real_table_ready():
    if not DB_PATH.exists():
        return False

    try:
        check_con = duckdb.connect(str(DB_PATH), read_only=True)
        ok = table_exists(check_con, ANALYTICS_TABLE)
        if ok:
            row_count = check_con.execute(f"select count(*) from {ANALYTICS_TABLE}").fetchone()[0]
            ok = row_count > 0
        check_con.close()
        return ok
    except Exception:
        return False


def run_cloud_extract(days=180):
    token = get_tushare_token()
    if not token:
        raise RuntimeError("未检测到 TUSHARE_TOKEN，请先在 Streamlit Cloud Secrets 中配置。")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "src.extract",
        "--days",
        str(days),
    ]

    result = subprocess.run(
        cmd,
        cwd=str(ROOT_DIR),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=1200,
    )

    if result.returncode != 0:
        error_message = result.stderr or result.stdout or "未知错误"
        raise RuntimeError(error_message[-4000:])

    return result.stdout[-4000:]


def ensure_demo_data(con):
    con.execute(
        f"""
        create table if not exists {DEMO_TABLE} (
            ts_code varchar,
            trade_date date,
            name varchar,
            industry varchar,
            market varchar,
            close double,
            pct_chg double,
            amount_100m double,
            amplitude double,
            is_up boolean,
            is_limit_up_proxy boolean,
            is_limit_down_proxy boolean,
            net_mf_amount_100m double
        )
        """
    )
    if con.execute(f"select count(*) from {DEMO_TABLE}").fetchone()[0] > 0:
        return

    demo_df = pd.DataFrame(
        [
            ["000001.SZ", "2026-06-12", "平安银行", "银行", "主板", 12.3, 1.8, 25.6, 3.1, True, False, False, 0.8],
            ["600519.SH", "2026-06-12", "贵州茅台", "白酒", "主板", 1520.0, -0.7, 42.1, 2.2, False, False, False, -1.2],
            ["300750.SZ", "2026-06-12", "宁德时代", "电池", "创业板", 188.4, 4.6, 56.8, 6.7, True, False, False, 2.4],
            ["688981.SH", "2026-06-12", "中芯国际", "半导体", "科创板", 51.2, 7.9, 33.5, 9.5, True, False, False, 1.7],
            ["002594.SZ", "2026-06-12", "比亚迪", "汽车", "主板", 251.6, -2.1, 38.2, 4.3, False, False, False, -0.9],
        ],
        columns=[
            "ts_code",
            "trade_date",
            "name",
            "industry",
            "market",
            "close",
            "pct_chg",
            "amount_100m",
            "amplitude",
            "is_up",
            "is_limit_up_proxy",
            "is_limit_down_proxy",
            "net_mf_amount_100m",
        ],
    )
    demo_df["trade_date"] = pd.to_datetime(demo_df["trade_date"])
    con.execute(f"insert into {DEMO_TABLE} select * from demo_df")


def choose_source_table(con):
    if table_exists(con, ANALYTICS_TABLE):
        row_count = con.execute(f"select count(*) from {ANALYTICS_TABLE}").fetchone()[0]
        if row_count > 0:
            return ANALYTICS_TABLE, "Tushare / DuckDB 真实数据表"

    ensure_demo_data(con)
    return DEMO_TABLE, "DuckDB 示例数据表"


def load_market_data(con, table_name):
    columns = {
        row[0]
        for row in con.execute(
            """
            select column_name
            from information_schema.columns
            where table_name = ?
            """,
            [table_name],
        ).fetchall()
    }
    net_flow_expr = "net_mf_amount_100m" if "net_mf_amount_100m" in columns else "null::double as net_mf_amount_100m"

    return con.execute(
        f"""
        select
            ts_code,
            trade_date,
            coalesce(name, ts_code) as name,
            industry,
            market,
            close,
            pct_chg,
            amount_100m,
            amplitude,
            is_up,
            is_limit_up_proxy,
            is_limit_down_proxy,
            {net_flow_expr}
        from {table_name}
        order by trade_date desc, amount_100m desc nulls last
        """
    ).df()


def load_index_data(con):
    if not table_exists(con, "analytics_index_daily"):
        return pd.DataFrame()
    df = con.execute(
        """
        select
            ts_code,
            index_name,
            trade_date,
            close,
            pct_chg,
            amount_100m
        from analytics_index_daily
        order by trade_date
        """
    ).df()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    return df


def load_quality_report(con):
    if not table_exists(con, "data_quality_report"):
        return pd.DataFrame()
    return con.execute(
        """
        select
            generated_at,
            table_name,
            metric,
            value,
            detail
        from data_quality_report
        order by generated_at desc, table_name, metric
        """
    ).df()


def clean_market_data(df):
    cleaned = df.copy()
    cleaned["trade_date"] = pd.to_datetime(cleaned["trade_date"], errors="coerce")
    for column in ["industry", "market", "name", "ts_code"]:
        cleaned[column] = cleaned[column].astype("string").replace({"": pd.NA, "None": pd.NA, "nan": pd.NA})

    cleaned["industry_label"] = cleaned["industry"].fillna("未分类行业")
    cleaned["market_label"] = cleaned["market"].fillna("未知板块")

    for column in ["close", "pct_chg", "amount_100m", "amplitude", "net_mf_amount_100m"]:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned["is_up"] = cleaned["is_up"].fillna(cleaned["pct_chg"] > 0).astype(bool)
    cleaned["is_limit_up_proxy"] = cleaned["is_limit_up_proxy"].fillna(cleaned["pct_chg"] >= 9.8).astype(bool)
    cleaned["is_limit_down_proxy"] = cleaned["is_limit_down_proxy"].fillna(cleaned["pct_chg"] <= -9.8).astype(bool)
    return cleaned


def format_amount(value):
    if pd.isna(value):
        return "-"
    return f"{value:,.2f} 亿"


def format_pct(value):
    if pd.isna(value):
        return "-"
    return f"{value:.2f}%"


def style_plotly(fig):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial", "color": INK},
        title={"font": {"size": 15, "color": INK}},
        margin={"l": 30, "r": 20, "t": 55, "b": 35},
        colorway=[ACCENT, "#1f4e79", "#2d6a73", "#8a6f3d", "#8c4f3d"],
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def render_metric(label, value, note=None):
    note_html = f"<div class='metric-note'>{note}</div>" if note else ""
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{label}</div>
          <div class="metric-value">{value}</div>
          {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def localize_sql_result(df):
    result = df.copy()
    for column in result.columns:
        if "date" in column.lower():
            converted = pd.to_datetime(result[column], errors="coerce")
            if converted.notna().any():
                result[column] = converted.dt.strftime("%Y-%m-%d").fillna(result[column].astype(str))
    return result.rename(columns={column: COLUMN_LABELS.get(column, column) for column in result.columns})


def dataframe_to_csv_bytes(df):
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


st.set_page_config(page_title="A股市场结构分析终端", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px; }
    .terminal-hero {
        background: linear-gradient(135deg, #101827 0%, #182338 55%, #3a2e18 100%);
        border: 1px solid rgba(214, 168, 79, 0.35);
        border-radius: 8px;
        padding: 24px 28px;
        margin-bottom: 22px;
        color: white;
    }
    .terminal-kicker {
        color: #d6a84f;
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .terminal-title { font-size: 32px; font-weight: 760; line-height: 1.15; margin: 0; }
    .terminal-subtitle { color: #c7d0df; margin-top: 10px; font-size: 14px; }
    .metric-card {
        border: 1px solid #d9dee7;
        border-top: 3px solid #d6a84f;
        border-radius: 8px;
        padding: 14px 16px;
        background: #ffffff;
        min-height: 106px;
    }
    .metric-label { color: #6f7a8a; font-size: 13px; margin-bottom: 8px; }
    .metric-value { color: #172033; font-size: 25px; font-weight: 720; }
    .metric-note { color: #8b95a5; font-size: 12px; margin-top: 6px; }
    div[data-testid="stDataFrame"] { border: 1px solid #e2e7ef; border-radius: 8px; }
    h2, h3 { color: #172033; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("数据更新")
    st.caption("云端部署版可通过 Tushare Token 拉取真实 A 股数据。")

    update_days = st.number_input(
        "拉取最近 N 天数据",
        min_value=30,
        max_value=365,
        value=180,
        step=30,
    )

if st.button("拉取 / 更新真实数据", type="primary"):
    try:
        close_cached_connection()

        with st.spinner("正在云端拉取 Tushare 数据并生成 DuckDB，请稍等..."):
            log_text = run_cloud_extract(days=int(update_days))

        close_cached_connection()
        st.success("真实数据更新完成，正在刷新页面。")

        with st.expander("查看抽取日志"):
            st.code(log_text)

        st.rerun()

    except Exception as exc:
        st.error("真实数据更新失败。")
        st.code(str(exc))

con = get_connection()
source_table, source_label = choose_source_table(con)
market_df = clean_market_data(load_market_data(con, source_table))
index_df = load_index_data(con)
quality_report_df = load_quality_report(con)

with st.sidebar:
    st.subheader("筛选条件")
    st.caption("基于当前 Tushare 股票行情权限构建。")
    trade_dates = sorted(market_df["trade_date"].dropna().dt.date.unique().tolist(), reverse=True)
    selected_date = st.selectbox("交易日期", trade_dates, index=0 if trade_dates else None)
    industries = sorted(market_df["industry_label"].dropna().unique().tolist())
    selected_industries = st.multiselect("行业", industries, default=industries)
    markets = sorted(market_df["market_label"].dropna().unique().tolist())
    selected_markets = st.multiselect("板块", markets, default=markets)

filtered_base_df = market_df[
    market_df["industry_label"].isin(selected_industries)
    & market_df["market_label"].isin(selected_markets)
].copy()

filtered_df = filtered_base_df[filtered_base_df["trade_date"].dt.date == selected_date].copy()

st.markdown(
    f"""
    <div class="terminal-hero">
      <div class="terminal-kicker">A股市场数据台</div>
      <h1 class="terminal-title">A股市场结构与资金风格分析终端</h1>
      <div class="terminal-subtitle">
        数据源：{source_label} | 交易日期：{selected_date} | 数据库：{DB_PATH}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

total_turnover = filtered_df["amount_100m"].sum()
avg_return = filtered_df["pct_chg"].mean()
up_ratio = filtered_df["is_up"].mean() if len(filtered_df) else float("nan")
limit_up_count = int(filtered_df["is_limit_up_proxy"].sum()) if len(filtered_df) else 0
net_flow = filtered_df["net_mf_amount_100m"].sum(min_count=1)

metric_cols = st.columns(5)
with metric_cols[0]:
    render_metric("股票数量", f"{len(filtered_df):,}", "当前筛选范围")
with metric_cols[1]:
    render_metric("成交额", format_amount(total_turnover), "单位：人民币亿元")
with metric_cols[2]:
    render_metric("平均涨跌幅", format_pct(avg_return), "等权平均")
with metric_cols[3]:
    render_metric("上涨占比", "-" if pd.isna(up_ratio) else f"{up_ratio:.1%}", "上涨股票 / 样本股票")
with metric_cols[4]:
    render_metric("涨停代理数", f"{limit_up_count:,}", "涨跌幅 >= 9.8%")

if pd.notna(net_flow):
    st.caption(f"当前筛选范围内可用资金净流入：{net_flow:,.2f} 亿元")
else:
    st.caption("资金流字段为可选数据；即使接口不可用，价格和行业分析仍可正常使用。")

industry_df = (
    filtered_df.groupby("industry_label", as_index=False)
    .agg(
        stock_count=("ts_code", "count"),
        turnover_100m=("amount_100m", "sum"),
        avg_return=("pct_chg", "mean"),
        up_ratio=("is_up", "mean"),
        limit_up_count=("is_limit_up_proxy", "sum"),
        net_flow_100m=("net_mf_amount_100m", "sum"),
    )
    .sort_values("turnover_100m", ascending=False)
)

trend_df = (
    filtered_base_df.groupby("trade_date", as_index=False)
    .agg(
        stock_count=("ts_code", "count"),
        turnover_100m=("amount_100m", "sum"),
        avg_return=("pct_chg", "mean"),
        up_ratio=("is_up", "mean"),
        limit_up_count=("is_limit_up_proxy", "sum"),
        net_flow_100m=("net_mf_amount_100m", "sum"),
    )
    .sort_values("trade_date")
)
trend_df = add_rolling_zscore(trend_df, "turnover_100m", window=20, min_periods=10)
trend_df = add_rolling_zscore(trend_df, "avg_return", window=20, min_periods=10)
trend_df = add_rolling_zscore(trend_df, "up_ratio", window=20, min_periods=10)

latest_trend = trend_df[trend_df["trade_date"].dt.date == selected_date].tail(1)
if latest_trend.empty:
    latest_trend = trend_df.dropna(subset=["trade_date"]).tail(1)
latest_turnover_z = latest_trend["turnover_100m_z20"].iloc[0] if not latest_trend.empty else float("nan")
latest_return_z = latest_trend["avg_return_z20"].iloc[0] if not latest_trend.empty else float("nan")
latest_up_ratio_z = latest_trend["up_ratio_z20"].iloc[0] if not latest_trend.empty else float("nan")
up_ratio_half_life = estimate_ar1_half_life(trend_df["up_ratio"])
risk_feature_df = build_stock_risk_features(filtered_base_df)
risk_today_df = risk_feature_df[risk_feature_df["trade_date"].dt.date == selected_date].copy()
risk_today_df["risk_reason"] = risk_today_df.apply(build_risk_reason, axis=1)
risk_alert_df = risk_today_df[risk_today_df["high_risk_flag"]].copy()
risk_ratio = len(risk_alert_df) / len(risk_today_df) if len(risk_today_df) else float("nan")

risk_ratio_by_date = (
    risk_feature_df.groupby("trade_date", as_index=False)
    .agg(risk_ratio=("high_risk_flag", "mean"))
    .sort_values("trade_date")
)
trend_signal_df = trend_df.merge(risk_ratio_by_date, on="trade_date", how="left")
trend_signal_df = add_market_score_columns(trend_signal_df)
trend_signal_df["market_regime"] = trend_signal_df.apply(
    lambda row: classify_market_regime(row["market_heat_score"], row.get("risk_ratio", float("nan"))),
    axis=1,
)
market_score_backtest_df = build_market_score_backtest(trend_signal_df)
selected_trend_signal = trend_signal_df[trend_signal_df["trade_date"].dt.date == selected_date].tail(1)
if selected_trend_signal.empty:
    selected_trend_signal = trend_signal_df.dropna(subset=["trade_date"]).tail(1)
latest_trend_row = selected_trend_signal.iloc[0].to_dict() if not selected_trend_signal.empty else {}
market_heat_score, market_score_components = build_market_score_detail(latest_trend_row, risk_ratio)
market_regime = classify_market_regime(market_heat_score, risk_ratio)
market_regime_note = regime_interpretation(market_regime)
industry_signal_df = build_industry_signal_frame(filtered_base_df, filtered_df)

tab_overview, tab_trend, tab_research, tab_risk, tab_sql, tab_quality, tab_report, tab_industry, tab_movers, tab_detail = st.tabs(
    ["市场总览", "半年趋势", "市场状态研究", "风险监控", "SQL样例", "数据质量", "研究报告", "行业透视", "涨跌幅榜", "个股明细"]
)

with tab_overview:
    signal_cols = st.columns(4)
    with signal_cols[0]:
        render_metric("市场温度评分", "-" if pd.isna(market_heat_score) else f"{market_heat_score:.1f}/100", market_regime)
    with signal_cols[1]:
        render_metric("状态解释", market_regime, market_regime_note)
    with signal_cols[2]:
        render_metric("风险样本占比", "-" if pd.isna(risk_ratio) else f"{risk_ratio:.1%}", "风险监控股票 / 当日样本")
    with signal_cols[3]:
        hot_industry = industry_signal_df.iloc[0]["industry_label"] if not industry_signal_df.empty else "-"
        hot_label = industry_signal_df.iloc[0]["signal_label"] if not industry_signal_df.empty else "样本不足"
        render_metric("最拥挤行业", hot_industry, hot_label)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            industry_df.head(15),
            x="industry_label",
            y="turnover_100m",
            title="成交额 Top 15 行业",
            labels={"industry_label": "行业", "turnover_100m": "成交额（亿元）"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    with col2:
        fig = px.histogram(
            filtered_df.dropna(subset=["pct_chg"]),
            x="pct_chg",
            nbins=40,
            title="个股涨跌幅分布",
            labels={"pct_chg": "日涨跌幅（%）"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    market_summary = (
        filtered_df.groupby("market_label", as_index=False)
        .agg(stock_count=("ts_code", "count"), turnover_100m=("amount_100m", "sum"), avg_return=("pct_chg", "mean"))
        .sort_values("turnover_100m", ascending=False)
    )
    fig = px.bar(
        market_summary,
        x="market_label",
        y="turnover_100m",
        color="avg_return",
        title="不同板块成交额与平均涨跌幅",
        labels={"market_label": "板块", "turnover_100m": "成交额（亿元）", "avg_return": "平均涨跌幅"},
    )
    st.plotly_chart(style_plotly(fig), use_container_width=True)

    with st.expander("查看市场温度评分标准"):
        st.markdown(
            """
            **评分口径**

            - `成交活跃度`：成交额在当前样本期中的历史分位数，权重 25%。
            - `市场宽度`：上涨占比在当前样本期中的历史分位数，权重 25%。
            - `收益强度`：等权平均涨跌幅在当前样本期中的历史分位数，权重 20%。
            - `涨停热度`：涨停代理占比在当前样本期中的历史分位数，权重 15%。
            - `风险控制`：风险预警股票占比分位数的反向得分，权重 15%。

            这版评分采用历史分位数而不是单纯 z-score 映射，目的是让不同交易日之间的冷热差异更明显。
            """
        )
        component_df = pd.DataFrame(market_score_components)
        component_df["权重"] = component_df["权重"].map(lambda value: f"{value:.0%}")
        st.dataframe(
            component_df.style.format({"分项得分": "{:.1f}"}),
            use_container_width=True,
            hide_index=True,
        )

with tab_trend:
    col1, col2 = st.columns(2)
    with col1:
        fig = px.line(
            trend_df,
            x="trade_date",
            y="turnover_100m",
            title="滚动区间成交额趋势",
            labels={"trade_date": "交易日期", "turnover_100m": "成交额（亿元）"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    with col2:
        fig = px.line(
            trend_df,
            x="trade_date",
            y="avg_return",
            title="滚动区间等权平均涨跌幅",
            labels={"trade_date": "交易日期", "avg_return": "平均涨跌幅（%）"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        fig = px.line(
            trend_df,
            x="trade_date",
            y="up_ratio",
            title="上涨占比趋势",
            labels={"trade_date": "交易日期", "up_ratio": "上涨占比"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    with col4:
        fig = px.bar(
            trend_df,
            x="trade_date",
            y="limit_up_count",
            title="涨停代理数趋势",
            labels={"trade_date": "交易日期", "limit_up_count": "涨停代理数"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    if trend_df["net_flow_100m"].notna().any():
        fig = px.line(
            trend_df,
            x="trade_date",
            y="net_flow_100m",
            title="资金净流入趋势",
            labels={"trade_date": "交易日期", "net_flow_100m": "资金净流入（亿元）"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    fig = px.line(
        trend_signal_df,
        x="trade_date",
        y="market_heat_score",
        color="market_regime",
        markers=True,
        title="市场温度评分趋势",
        labels={"trade_date": "交易日期", "market_heat_score": "市场温度评分", "market_regime": "市场状态"},
    )
    fig.add_hline(y=70, line_dash="dash", line_color="#b45309")
    fig.add_hline(y=35, line_dash="dash", line_color="#1f4e79")
    st.plotly_chart(style_plotly(fig), use_container_width=True)

    if not index_df.empty:
        index_window_df = index_df[index_df["trade_date"].dt.date.isin(trend_df["trade_date"].dt.date)].copy()
        if not index_window_df.empty:
            fig = px.line(
                index_window_df,
                x="trade_date",
                y="pct_chg",
                color="index_name",
                title="指数基准日涨跌幅",
                labels={"trade_date": "交易日期", "pct_chg": "日涨跌幅（%）", "index_name": "指数"},
            )
            st.plotly_chart(style_plotly(fig), use_container_width=True)
    else:
        st.caption("指数基准数据为可选数据；如需展示沪深300/中证500，请运行包含 index_daily 权限的数据抽取。")

with tab_research:
    st.subheader("均值回归与市场状态识别")
    st.caption(
        "这里使用 20 日滚动均值和滚动标准差构造 z-score："
        "z = (当前值 - 滚动均值) / 滚动标准差。z-score 可用于观察市场成交、收益和上涨占比是否处于相对极端状态。"
    )

    research_cols = st.columns(4)
    with research_cols[0]:
        render_metric("成交额 z-score", "-" if pd.isna(latest_turnover_z) else f"{latest_turnover_z:.2f}", classify_zscore(latest_turnover_z))
    with research_cols[1]:
        render_metric("平均涨跌幅 z-score", "-" if pd.isna(latest_return_z) else f"{latest_return_z:.2f}", classify_zscore(latest_return_z))
    with research_cols[2]:
        render_metric("上涨占比 z-score", "-" if pd.isna(latest_up_ratio_z) else f"{latest_up_ratio_z:.2f}", classify_zscore(latest_up_ratio_z))
    with research_cols[3]:
        half_life_value = up_ratio_half_life["half_life"]
        render_metric("上涨占比半衰期", "-" if pd.isna(half_life_value) else f"{half_life_value:.1f} 日", up_ratio_half_life["interpretation"])

    market_score_text = "-" if pd.isna(market_heat_score) else f"{market_heat_score:.1f}/100"
    risk_ratio_text = "-" if pd.isna(risk_ratio) else f"{risk_ratio:.1%}"
    st.info(
        f"当前市场状态识别为：{market_regime}。"
        f"市场温度评分 {market_score_text}，风险样本占比 {risk_ratio_text}。"
        f"{market_regime_note}"
    )

    col1, col2 = st.columns(2)
    with col1:
        fig = px.line(
            trend_df,
            x="trade_date",
            y=["turnover_100m", "turnover_100m_ma20"],
            title="成交额与 20 日滚动均值",
            labels={"trade_date": "交易日期", "value": "成交额（亿元）", "variable": "指标"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    with col2:
        fig = px.line(
            trend_df,
            x="trade_date",
            y="turnover_100m_z20",
            title="成交额 20 日 z-score",
            labels={"trade_date": "交易日期", "turnover_100m_z20": "z-score"},
        )
        fig.add_hline(y=2, line_dash="dash", line_color="#b45309")
        fig.add_hline(y=-2, line_dash="dash", line_color="#1f4e79")
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        fig = px.line(
            trend_df,
            x="trade_date",
            y=["avg_return", "avg_return_ma20"],
            title="等权平均涨跌幅与 20 日滚动均值",
            labels={"trade_date": "交易日期", "value": "涨跌幅（%）", "variable": "指标"},
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    with col4:
        ar_df = pd.DataFrame(
            {
                "当日上涨占比": trend_df["up_ratio"],
                "下一交易日上涨占比": trend_df["up_ratio"].shift(-1),
            }
        ).dropna()
        fig = px.scatter(
            ar_df,
            x="当日上涨占比",
            y="下一交易日上涨占比",
            title="上涨占比的一阶均值回复关系",
        )
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    st.markdown(
        """
        **研究口径说明**

        - `z-score > 2` 通常表示指标显著高于近期均值，可能代表交易拥挤、情绪过热或波动异常。
        - `z-score < -2` 通常表示指标显著低于近期均值，可能代表成交低迷或风险偏好收缩。
        - 半衰期来自一个简化 AR(1) 估计，用来描述上涨占比偏离均值后回归正常状态的大致速度。
        - 这些指标不是交易信号本身，更适合作为市场状态监控和研究解释变量。
        """
    )

    st.markdown(
        """
        **状态分层**

        - `80-100`：过热扩张。
        - `65-80`：Risk-on 偏强。
        - `55-65`：偏暖轮动。
        - `45-55`：结构分化。
        - `35-45`：偏弱震荡。
        - `0-35`：Risk-off 收缩。
        - 若风险样本占比超过 35%，会优先识别为 `过热高波动`、`高风险分化` 或 `风险释放`。
        """
    )

    st.subheader("市场温度分组验证")
    st.caption("按历史市场温度评分分组，观察各组下一交易日的等权平均涨跌幅和上涨占比。")
    if market_score_backtest_df.empty:
        st.info("当前样本不足，暂无法生成分组验证结果。")
    else:
        backtest_display_df = market_score_backtest_df.rename(
            columns={
                "bucket": "分组",
                "sample_count": "样本数",
                "score_min": "评分下限",
                "score_max": "评分上限",
                "avg_next_return": "下一日平均涨跌幅",
                "avg_next_up_ratio": "下一日上涨占比",
            }
        )
        st.dataframe(
            backtest_display_df.style.format(
                {
                    "评分下限": "{:.1f}",
                    "评分上限": "{:.1f}",
                    "下一日平均涨跌幅": "{:.2f}",
                    "下一日上涨占比": "{:.1%}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

with tab_risk:
    st.subheader("风险监控与异常识别")
    st.caption("基于滚动 20 日窗口识别异常涨跌幅、成交放量、高波动和深度回撤股票。")

    risk_cols = st.columns(4)
    with risk_cols[0]:
        render_metric("风险预警股票", f"{len(risk_alert_df):,}", "任一风控标记触发")
    with risk_cols[1]:
        render_metric("异常涨跌幅", f"{int(risk_today_df['abnormal_return_flag'].sum()):,}", "|return z-score| >= 2")
    with risk_cols[2]:
        render_metric("异常放量", f"{int(risk_today_df['abnormal_turnover_flag'].sum()):,}", "turnover z-score >= 2")
    with risk_cols[3]:
        render_metric("深度回撤", f"{int(risk_today_df['deep_drawdown_flag'].sum()):,}", "20 日回撤 <= -20%")

    risk_rank_df = risk_today_df.sort_values(
        ["high_risk_flag", "return_vol_20d", "turnover_zscore_20d"],
        ascending=[False, False, False],
    ).head(80)
    risk_display_df = risk_rank_df[
        [
            "ts_code",
            "name",
            "industry_label",
            "pct_chg",
            "amount_100m",
            "return_vol_20d",
            "return_zscore_20d",
            "turnover_zscore_20d",
            "drawdown_20d",
            "consecutive_down_days",
            "high_risk_flag",
            "risk_reason",
        ]
    ].rename(
        columns={
            "ts_code": "股票代码",
            "name": "股票名称",
            "industry_label": "行业",
            "pct_chg": "当日涨跌幅",
            "amount_100m": "成交额_亿元",
            "return_vol_20d": "20日波动率",
            "return_zscore_20d": "涨跌幅z值",
            "turnover_zscore_20d": "成交额z值",
            "drawdown_20d": "20日回撤",
            "consecutive_down_days": "连续下跌天数",
            "high_risk_flag": "风险标记",
            "risk_reason": "触发原因",
        }
    )
    st.dataframe(
        risk_display_df.style.format(
            {
                "当日涨跌幅": "{:.2f}",
                "成交额_亿元": "{:,.2f}",
                "20日波动率": "{:.2f}",
                "涨跌幅z值": "{:.2f}",
                "成交额z值": "{:.2f}",
                "20日回撤": "{:.2f}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "下载风险预警表 CSV",
        data=dataframe_to_csv_bytes(risk_display_df),
        file_name=f"risk_alerts_{selected_date}.csv",
        mime="text/csv",
    )

    risk_industry_df = (
        risk_today_df.groupby("industry_label", as_index=False)
        .agg(
            risk_count=("high_risk_flag", "sum"),
            avg_vol_20d=("return_vol_20d", "mean"),
            avg_drawdown_20d=("drawdown_20d", "mean"),
        )
        .sort_values("risk_count", ascending=False)
        .head(20)
    )
    fig = px.bar(
        risk_industry_df,
        x="industry_label",
        y="risk_count",
        title="风险预警股票数量 Top 20 行业",
        labels={"industry_label": "行业", "risk_count": "风险预警股票数量"},
    )
    st.plotly_chart(style_plotly(fig), use_container_width=True)

with tab_sql:
    st.subheader("SQL 分析样例")
    st.caption("这些 SQL 用于展示窗口函数、分组聚合、异常识别和风控查询能力。默认样例会跟随左侧选择的交易日期。")

    sql_examples = {
        "行业市场结构": f"""
select
    coalesce(industry, '未分类行业') as industry,
    count(*) as stock_count,
    round(sum(amount_100m), 2) as turnover_100m,
    round(avg(pct_chg), 2) as avg_return,
    round(avg(case when is_up then 1 else 0 end), 4) as up_ratio
from analytics_market_daily
where trade_date = date '{selected_date}'
group by coalesce(industry, '未分类行业')
order by turnover_100m desc;
""",
        "市场温度评分框架": f"""
with daily_market as (
    select
        trade_date,
        count(*) as stock_count,
        sum(amount_100m) as turnover_100m,
        avg(pct_chg) as avg_return,
        avg(case when is_up then 1 else 0 end) as up_ratio,
        sum(case when is_limit_up_proxy then 1 else 0 end) as limit_up_count
    from analytics_market_daily
    group by trade_date
),
score_base as (
    select
        *,
        limit_up_count / nullif(stock_count, 0) as limit_up_intensity,
        percent_rank() over (order by turnover_100m) * 100 as turnover_score,
        percent_rank() over (order by avg_return) * 100 as return_score,
        percent_rank() over (order by up_ratio) * 100 as breadth_score,
        percent_rank() over (order by limit_up_count / nullif(stock_count, 0)) * 100 as limit_up_score
    from daily_market
)
select
    trade_date,
    round(turnover_score, 2) as turnover_score,
    round(breadth_score, 2) as breadth_score,
    round(return_score, 2) as return_score,
    round(limit_up_score, 2) as limit_up_score,
    round(
        0.25 * turnover_score
        + 0.25 * breadth_score
        + 0.20 * return_score
        + 0.15 * limit_up_score,
        2
    ) as market_heat_score_without_risk
from score_base
where trade_date = date '{selected_date}';
""",
        "20日波动率监控": f"""
with risk_base as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        pct_chg,
        stddev(pct_chg) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as vol_20d
    from analytics_market_daily
)
select *
from risk_base
where trade_date = date '{selected_date}'
order by vol_20d desc
limit 50;
""",
        "异常成交放量": f"""
with turnover_z as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        amount_100m,
        avg(amount_100m) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as avg_amount_20d,
        stddev(amount_100m) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as std_amount_20d
    from analytics_market_daily
)
select
    *,
    (amount_100m - avg_amount_20d) / nullif(std_amount_20d, 0) as amount_zscore
from turnover_z
where trade_date = date '{selected_date}'
order by amount_zscore desc
limit 50;
""",
        "行业轮动强弱": f"""
select
    coalesce(industry, '未分类行业') as industry,
    count(*) as observations,
    round(avg(pct_chg), 2) as avg_return,
    round(sum(amount_100m), 2) as turnover_100m,
    round(avg(case when is_up then 1 else 0 end), 4) as up_ratio
from analytics_market_daily
where trade_date between date '{selected_date}' - interval 20 day and date '{selected_date}'
group by coalesce(industry, '未分类行业')
having count(*) >= 20
order by avg_return desc;
""",
        "行业拥挤度识别": f"""
with industry_daily as (
    select
        trade_date,
        coalesce(industry, '未分类行业') as industry,
        count(*) as stock_count,
        sum(amount_100m) as turnover_100m,
        avg(pct_chg) as avg_return,
        avg(case when is_up then 1 else 0 end) as up_ratio
    from analytics_market_daily
    group by trade_date, coalesce(industry, '未分类行业')
),
industry_signal as (
    select
        *,
        (turnover_100m - avg(turnover_100m) over w) / nullif(stddev(turnover_100m) over w, 0) as crowding_z20,
        avg_return - avg(avg_return) over w as relative_return_20d
    from industry_daily
    window w as (
        partition by industry
        order by trade_date
        rows between 19 preceding and current row
    )
)
select
    industry,
    stock_count,
    round(turnover_100m, 2) as turnover_100m,
    round(avg_return, 2) as avg_return,
    round(up_ratio, 4) as up_ratio,
    round(crowding_z20, 2) as crowding_z20,
    round(relative_return_20d, 2) as relative_return_20d
from industry_signal
where trade_date = date '{selected_date}'
order by crowding_z20 desc nulls last;
""",
        "资金流背离": f"""
select
    ts_code,
    name,
    industry,
    trade_date,
    pct_chg,
    amount_100m,
    net_mf_amount_100m
from analytics_market_daily
where trade_date = date '{selected_date}'
  and pct_chg > 0
  and net_mf_amount_100m < 0
order by amount_100m desc
limit 50;
""",
        "连续下跌股票": f"""
with down_flag as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        pct_chg,
        case when pct_chg < 0 then 1 else 0 end as is_down
    from analytics_market_daily
),
down_group as (
    select
        *,
        sum(case when is_down = 0 then 1 else 0 end) over (
            partition by ts_code
            order by trade_date
        ) as reset_group
    from down_flag
),
down_count as (
    select
        *,
        sum(is_down) over (
            partition by ts_code, reset_group
            order by trade_date
        ) as consecutive_down_days
    from down_group
)
select
    ts_code,
    name,
    industry,
    trade_date,
    pct_chg,
    consecutive_down_days
from down_count
where trade_date = date '{selected_date}'
order by consecutive_down_days desc, pct_chg asc
limit 50;
""",
        "高波动高成交": f"""
with risk_base as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        pct_chg,
        amount_100m,
        stddev(pct_chg) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as vol_20d,
        avg(amount_100m) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as avg_amount_20d
    from analytics_market_daily
)
select
    *,
    amount_100m / nullif(avg_amount_20d, 0) as turnover_multiple
from risk_base
where trade_date = date '{selected_date}'
order by vol_20d desc, turnover_multiple desc
limit 50;
""",
    }

    selected_sql = st.selectbox("选择 SQL 样例", list(sql_examples.keys()))
    sql_text = st.text_area(
        "SQL 编辑器（当前连接 DuckDB，不是 SQLite）",
        value=sql_examples[selected_sql].strip(),
        height=280,
    )
    run_sql = st.button("运行 SQL", type="primary")
    if run_sql:
        normalized_sql = sql_text.strip().lower()
        if not (normalized_sql.startswith("select") or normalized_sql.startswith("with")):
            st.error("出于安全考虑，页面内 SQL 运行器只允许 SELECT / WITH 查询。")
        else:
            try:
                result_df = con.execute(sql_text).df()
                display_result_df = localize_sql_result(result_df)
                st.success(f"查询成功，返回 {len(result_df):,} 行。")
                st.dataframe(display_result_df, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"SQL 执行失败：{exc}")
                st.info(
                    "当前项目数据表在 DuckDB 文件中，不在 SQLite 默认连接里。"
                    "请确认查询表名为 analytics_market_daily，或先运行 py -m src.extract 生成数据。"
                )

    with st.expander("查看可用表和字段"):
        tables_df = con.execute("show tables").df()
        st.dataframe(tables_df, use_container_width=True, hide_index=True)
        if table_exists(con, ANALYTICS_TABLE):
            schema_df = con.execute(f"describe {ANALYTICS_TABLE}").df()
            st.dataframe(schema_df, use_container_width=True, hide_index=True)

with tab_quality:
    st.subheader("数据质量监控")
    st.caption("展示抽取后生成的表级数据质量指标，包括行数、日期范围、缺失率和主键重复情况。")

    if quality_report_df.empty:
        st.info("暂无数据质量报告。运行 `py -m src.extract` 后会生成 data_quality_report 表。")
    else:
        latest_quality_time = quality_report_df["generated_at"].max()
        latest_quality_df = quality_report_df[quality_report_df["generated_at"] == latest_quality_time].copy()
        st.caption(f"最近生成时间：{latest_quality_time}")
        st.dataframe(
            latest_quality_df.rename(
                columns={
                    "generated_at": "生成时间",
                    "table_name": "表名",
                    "metric": "指标",
                    "value": "数值",
                    "detail": "说明",
                }
            ).style.format({"数值": "{:.4f}"}),
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "下载数据质量报告 CSV",
            data=dataframe_to_csv_bytes(latest_quality_df),
            file_name=f"data_quality_report_{selected_date}.csv",
            mime="text/csv",
        )

with tab_report:
    st.subheader("自动研究报告")
    top_industry_name = industry_df.iloc[0]["industry_label"] if not industry_df.empty else "-"
    top_industry_turnover = industry_df.iloc[0]["turnover_100m"] if not industry_df.empty else float("nan")
    top_signal_industry = industry_signal_df.iloc[0]["industry_label"] if not industry_signal_df.empty else "-"
    top_signal_label = industry_signal_df.iloc[0]["signal_label"] if not industry_signal_df.empty else "样本不足"
    top_signal_z = industry_signal_df.iloc[0]["crowding_z20"] if not industry_signal_df.empty else float("nan")
    risk_count = len(risk_alert_df)
    report_text = f"""
### 市场状态摘要

- 当前交易日为 **{selected_date}**，筛选范围内共有 **{len(filtered_df):,}** 只股票。
- 当日成交额合计 **{format_amount(total_turnover)}**，等权平均涨跌幅为 **{format_pct(avg_return)}**，上涨占比为 **{"-" if pd.isna(up_ratio) else f"{up_ratio:.1%}"}**。
- 市场温度评分为 **{"-" if pd.isna(market_heat_score) else f"{market_heat_score:.1f}/100"}**，状态识别为 **{market_regime}**。{market_regime_note}
- 成交额最高的行业为 **{top_industry_name}**，成交额约 **{format_amount(top_industry_turnover)}**。
- 当前成交最拥挤行业为 **{top_signal_industry}**，拥挤度 z-score 为 **{"-" if pd.isna(top_signal_z) else f"{top_signal_z:.2f}"}**，信号标签：**{top_signal_label}**。
- 当前成交额 z-score 为 **{"-" if pd.isna(latest_turnover_z) else f"{latest_turnover_z:.2f}"}**，状态判断：**{classify_zscore(latest_turnover_z)}**。
- 当前上涨占比 z-score 为 **{"-" if pd.isna(latest_up_ratio_z) else f"{latest_up_ratio_z:.2f}"}**，状态判断：**{classify_zscore(latest_up_ratio_z)}**。
- 风控模块识别出 **{risk_count:,}** 只风险预警股票，主要依据包括异常涨跌幅、异常放量、高波动和 20 日深度回撤。

### 研究解释

本项目将市场宽度、成交额、行业结构和个股风险指标纳入统一分析框架。滚动 z-score 用于衡量当前市场状态相对于近期历史分布的偏离程度；AR(1) 半衰期用于描述市场宽度指标偏离均值后的回归速度；行业拥挤度用于识别成交是否集中在少数方向；个股层面的风险监控则通过波动率、成交额 z-score、回撤和连续下跌天数识别潜在异常样本，并给出可解释的触发原因。
"""
    st.markdown(report_text)
    st.download_button(
        "下载研究报告 Markdown",
        data=report_text.encode("utf-8"),
        file_name=f"market_report_{selected_date}.md",
        mime="text/markdown",
    )

with tab_industry:
    st.subheader("行业轮动与拥挤度信号")
    st.caption("用行业成交额 20 日 z-score 衡量交易拥挤度，并结合行业平均收益和上涨占比给出状态标签。")

    if not industry_signal_df.empty:
        industry_signal_display_df = industry_signal_df[
            [
                "industry_label",
                "stock_count",
                "turnover_100m",
                "avg_return",
                "up_ratio",
                "crowding_z20",
                "relative_return_20d",
                "signal_label",
            ]
        ].rename(
            columns={
                "industry_label": "行业",
                "stock_count": "股票数量",
                "turnover_100m": "成交额_亿元",
                "avg_return": "平均涨跌幅",
                "up_ratio": "上涨占比",
                "crowding_z20": "拥挤度z值",
                "relative_return_20d": "相对20日收益",
                "signal_label": "信号标签",
            }
        )
        st.dataframe(
            industry_signal_display_df.style.format(
                {
                    "成交额_亿元": "{:,.2f}",
                    "平均涨跌幅": "{:.2f}",
                    "上涨占比": "{:.1%}",
                    "拥挤度z值": "{:.2f}",
                    "相对20日收益": "{:.2f}",
                },
                na_rep="-",
            ),
            use_container_width=True,
            hide_index=True,
        )

        fig = px.scatter(
            industry_signal_df,
            x="crowding_z20",
            y="avg_return",
            size="turnover_100m",
            color="signal_label",
            hover_name="industry_label",
            title="行业拥挤度 vs 当日收益",
            labels={
                "crowding_z20": "成交拥挤度 z-score",
                "avg_return": "平均涨跌幅（%）",
                "turnover_100m": "成交额（亿元）",
                "signal_label": "信号标签",
            },
        )
        fig.add_vline(x=2, line_dash="dash", line_color="#b45309")
        fig.add_hline(y=0, line_dash="dash", line_color="#6b7280")
        st.plotly_chart(style_plotly(fig), use_container_width=True)

    st.subheader("行业基础透视表")
    display_industry_df = industry_df.rename(
        columns={
            "industry_label": "行业",
            "stock_count": "股票数量",
            "turnover_100m": "成交额_亿元",
            "avg_return": "平均涨跌幅",
            "up_ratio": "上涨占比",
            "limit_up_count": "涨停代理数",
            "net_flow_100m": "资金净流入_亿元",
        }
    )
    st.dataframe(
        display_industry_df.style.format(
            {
                "成交额_亿元": "{:,.2f}",
                "平均涨跌幅": "{:.2f}",
                "上涨占比": "{:.1%}",
                "资金净流入_亿元": "{:,.2f}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "下载行业透视表 CSV",
        data=dataframe_to_csv_bytes(display_industry_df),
        file_name=f"industry_lens_{selected_date}.csv",
        mime="text/csv",
    )

with tab_movers:
    gainers, losers = st.columns(2)
    with gainers:
        st.subheader("涨幅榜")
        gainers_df = filtered_df.sort_values("pct_chg", ascending=False).head(20)
        gainers_df = gainers_df[["ts_code", "name", "industry_label", "close", "pct_chg", "amount_100m"]].rename(
            columns={
                "ts_code": "股票代码",
                "name": "股票名称",
                "industry_label": "行业",
                "close": "收盘价",
                "pct_chg": "涨跌幅",
                "amount_100m": "成交额_亿元",
            }
        )
        st.dataframe(
            gainers_df.style.format({"收盘价": "{:.2f}", "涨跌幅": "{:.2f}", "成交额_亿元": "{:,.2f}"}, na_rep="-"),
            use_container_width=True,
            hide_index=True,
        )

    with losers:
        st.subheader("跌幅榜")
        losers_df = filtered_df.sort_values("pct_chg", ascending=True).head(20)
        losers_df = losers_df[["ts_code", "name", "industry_label", "close", "pct_chg", "amount_100m"]].rename(
            columns={
                "ts_code": "股票代码",
                "name": "股票名称",
                "industry_label": "行业",
                "close": "收盘价",
                "pct_chg": "涨跌幅",
                "amount_100m": "成交额_亿元",
            }
        )
        st.dataframe(
            losers_df.style.format({"收盘价": "{:.2f}", "涨跌幅": "{:.2f}", "成交额_亿元": "{:,.2f}"}, na_rep="-"),
            use_container_width=True,
            hide_index=True,
        )

with tab_detail:
    search = st.text_input("搜索股票名称 / 代码", "")
    display_df = filtered_df.copy()
    if search:
        mask = (
            display_df["name"].fillna("").str.contains(search, case=False, regex=False)
            | display_df["ts_code"].fillna("").str.contains(search, case=False, regex=False)
        )
        display_df = display_df[mask]

    display_df = display_df[
        [
            "ts_code",
            "name",
            "industry_label",
            "market_label",
            "close",
            "pct_chg",
            "amount_100m",
            "amplitude",
            "net_mf_amount_100m",
        ]
    ].rename(
        columns={
            "ts_code": "股票代码",
            "name": "股票名称",
            "industry_label": "行业",
            "market_label": "板块",
            "close": "收盘价",
            "pct_chg": "涨跌幅",
            "amount_100m": "成交额_亿元",
            "amplitude": "振幅",
            "net_mf_amount_100m": "资金净流入_亿元",
        }
    )

    st.dataframe(
        display_df.style.format(
            {
                "收盘价": "{:.2f}",
                "涨跌幅": "{:.2f}",
                "成交额_亿元": "{:,.2f}",
                "振幅": "{:.2f}",
                "资金净流入_亿元": "{:,.2f}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )
