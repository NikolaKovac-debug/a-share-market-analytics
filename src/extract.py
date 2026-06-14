import argparse
import shutil
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.config import DB_PATH, PROCESSED_DIR, RAW_DIR, SNAPSHOT_DIR
from src.database import connect, write_dataframe
from src.quality import build_quality_report
from src.tushare_client import TushareClient


DEFAULT_DATASETS = {
    "stock_basic": {
        "api": "stock_basic",
        "params": {
            "exchange": "",
            "list_status": "L",
            "fields": "ts_code,symbol,name,area,industry,market,list_date",
        },
        "accepts_dates": False,
        "required": True,
    },
    "daily": {
        "api": "daily",
        "params": {},
        "accepts_dates": True,
        "required": True,
    },
    "moneyflow": {
        "api": "moneyflow",
        "params": {},
        "accepts_dates": True,
        "required": False,
    },
    "limit_list_d": {
        "api": "limit_list_d",
        "params": {},
        "accepts_dates": True,
        "required": False,
    },
    "index_daily": {
        "api": "index_daily",
        "params": {"fields": "ts_code,trade_date,close,pct_chg,vol,amount"},
        "accepts_dates": True,
        "required": False,
    },
}

DAILY_SLICE_DATASETS = {"daily", "moneyflow", "limit_list_d", "index_daily"}
BENCHMARK_INDEX_CODES = ["000300.SH", "000905.SH"]


NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]


def build_sample_data(days: int = 60) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(42)
    stocks = pd.DataFrame(
        [
            ["000001.SZ", "000001", "平安银行", "深圳", "银行", "主板", "19910403"],
            ["600519.SH", "600519", "贵州茅台", "贵州", "白酒", "主板", "20010827"],
            ["300750.SZ", "300750", "宁德时代", "福建", "电池", "创业板", "20180611"],
            ["688981.SH", "688981", "中芯国际", "上海", "半导体", "科创板", "20200716"],
            ["002594.SZ", "002594", "比亚迪", "深圳", "汽车", "主板", "20110630"],
            ["601318.SH", "601318", "中国平安", "深圳", "保险", "主板", "20070301"],
            ["600036.SH", "600036", "招商银行", "深圳", "银行", "主板", "20020409"],
            ["300059.SZ", "300059", "东方财富", "上海", "互联网", "创业板", "20100319"],
        ],
        columns=["ts_code", "symbol", "name", "area", "industry", "market", "list_date"],
    )

    trade_dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    rows = []
    flow_rows = []
    base_prices = rng.uniform(20, 200, size=len(stocks))
    for idx, stock in stocks.iterrows():
        price = base_prices[idx]
        for trade_date in trade_dates:
            pct_chg = float(rng.normal(0.05, 2.2))
            if rng.random() < 0.015:
                pct_chg += float(rng.choice([-9.8, 9.8]))
            pre_close = price
            close = max(1, pre_close * (1 + pct_chg / 100))
            high = max(pre_close, close) * (1 + abs(float(rng.normal(0.01, 0.01))))
            low = min(pre_close, close) * (1 - abs(float(rng.normal(0.01, 0.01))))
            open_price = pre_close * (1 + float(rng.normal(0, 0.01)))
            amount = max(10000, float(rng.lognormal(11.5, 0.6)))
            vol = amount / close * 100
            rows.append(
                [
                    stock["ts_code"],
                    trade_date.strftime("%Y%m%d"),
                    open_price,
                    high,
                    low,
                    close,
                    pre_close,
                    close - pre_close,
                    pct_chg,
                    vol,
                    amount,
                ]
            )
            flow_rows.append(
                [
                    stock["ts_code"],
                    trade_date.strftime("%Y%m%d"),
                    float(rng.normal(0, amount * 0.05)),
                ]
            )
            price = close

    daily = pd.DataFrame(
        rows,
        columns=[
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ],
    )
    moneyflow = pd.DataFrame(flow_rows, columns=["ts_code", "trade_date", "net_mf_amount"])
    return stocks, daily, moneyflow


def run_sample(days: int) -> None:
    con = connect()
    stock_basic_df, daily_df, moneyflow_df = build_sample_data(days)
    write_dataframe(con, "raw_stock_basic", stock_basic_df)
    write_dataframe(con, "raw_daily", daily_df)
    write_dataframe(con, "raw_moneyflow", moneyflow_df)
    build_market_table(con, stock_basic_df, daily_df, moneyflow_df)
    con.close()
    snapshot_database()
    print(f"Built sample analytics_market_daily with {len(daily_df)} rows.")


def save_raw_dataset(df: pd.DataFrame, dataset_name: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RAW_DIR / f"{dataset_name}_{timestamp}.csv"
    parquet_path = RAW_DIR / f"{dataset_name}_{timestamp}.parquet"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_parquet(parquet_path, index=False)


def save_processed_dataset(df: pd.DataFrame, dataset_name: str) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parquet_path = PROCESSED_DIR / f"{dataset_name}_{timestamp}.parquet"
    df.to_parquet(parquet_path, index=False)


def snapshot_database() -> None:
    if not DB_PATH.exists():
        return
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = SNAPSHOT_DIR / f"market_analytics_{timestamp}.duckdb"
    shutil.copy2(DB_PATH, snapshot_path)


def fetch_by_trade_date(
    client: TushareClient,
    api_name: str,
    base_params: dict,
    start_date: str,
    end_date: str,
    pause: float,
) -> pd.DataFrame:
    frames = []
    trade_dates = pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date), freq="D")
    for trade_date in trade_dates:
        trade_date_text = trade_date.strftime("%Y%m%d")
        params = dict(base_params)
        params["trade_date"] = trade_date_text
        try:
            frame = client.query(api_name, **params)
        except Exception as exc:
            print(f"  skipped {api_name} {trade_date_text}: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)
        if pause > 0:
            time.sleep(pause)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def fetch_dataset(
    client: TushareClient,
    dataset_name: str,
    start_date: str | None,
    end_date: str | None,
    pause: float,
) -> pd.DataFrame:
    if dataset_name == "index_daily":
        return fetch_index_daily(client, start_date, end_date, pause)

    dataset = DEFAULT_DATASETS[dataset_name]
    params = dict(dataset["params"])
    if dataset_name in DAILY_SLICE_DATASETS and start_date and end_date:
        return fetch_by_trade_date(client, dataset["api"], params, start_date, end_date, pause)

    if dataset.get("accepts_dates") and start_date:
        params["start_date"] = start_date
    if dataset.get("accepts_dates") and end_date:
        params["end_date"] = end_date

    return client.query(dataset["api"], **params)


def fetch_index_daily(
    client: TushareClient,
    start_date: str | None,
    end_date: str | None,
    pause: float,
) -> pd.DataFrame:
    frames = []
    for ts_code in BENCHMARK_INDEX_CODES:
        params = dict(DEFAULT_DATASETS["index_daily"]["params"])
        params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            frame = client.query("index_daily", **params)
        except Exception as exc:
            print(f"  skipped index_daily {ts_code}: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)
        if pause > 0:
            time.sleep(pause)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def normalize_stock_basic(stock_basic_df: pd.DataFrame) -> pd.DataFrame:
    df = stock_basic_df.copy()
    for column in ["ts_code", "symbol", "name", "area", "industry", "market", "list_date"]:
        if column not in df.columns:
            df[column] = pd.NA

    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    return df[["ts_code", "symbol", "name", "area", "industry", "market", "list_date"]].drop_duplicates("ts_code")


def normalize_daily(daily_df: pd.DataFrame) -> pd.DataFrame:
    df = daily_df.copy()
    for column in ["ts_code", "trade_date", *NUMERIC_COLUMNS]:
        if column not in df.columns:
            df[column] = pd.NA

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df[["ts_code", "trade_date", *NUMERIC_COLUMNS]].dropna(subset=["ts_code", "trade_date"])


def normalize_moneyflow(moneyflow_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if moneyflow_df is None or moneyflow_df.empty:
        return None

    df = moneyflow_df.copy()
    if "ts_code" not in df.columns or "trade_date" not in df.columns:
        return None

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    candidate_columns = [
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    ]
    keep_columns = ["ts_code", "trade_date"]
    for column in candidate_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
            keep_columns.append(column)

    if len(keep_columns) == 2:
        return None
    return df[keep_columns].dropna(subset=["ts_code", "trade_date"])


def normalize_index_daily(index_daily_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if index_daily_df is None or index_daily_df.empty:
        return None
    df = index_daily_df.copy()
    for column in ["ts_code", "trade_date", "close", "pct_chg", "vol", "amount"]:
        if column not in df.columns:
            df[column] = pd.NA

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for column in ["close", "pct_chg", "vol", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    index_name_map = {"000300.SH": "沪深300", "000905.SH": "中证500"}
    df["index_name"] = df["ts_code"].map(index_name_map).fillna(df["ts_code"])
    df["amount_100m"] = df["amount"] / 100000
    return df[["ts_code", "index_name", "trade_date", "close", "pct_chg", "vol", "amount_100m"]].dropna(
        subset=["ts_code", "trade_date"]
    )


def build_market_table(
    con,
    stock_basic_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    moneyflow_df: pd.DataFrame | None = None,
    index_daily_df: pd.DataFrame | None = None,
) -> None:
    stock_df = normalize_stock_basic(stock_basic_df)
    price_df = normalize_daily(daily_df)

    analytics_df = price_df.merge(stock_df, on="ts_code", how="left")
    analytics_df["amount_100m"] = analytics_df["amount"] / 100000
    analytics_df["vol_100m_shares"] = analytics_df["vol"] / 1000000
    analytics_df["amplitude"] = (analytics_df["high"] - analytics_df["low"]) / analytics_df["pre_close"] * 100
    analytics_df["is_up"] = analytics_df["pct_chg"] > 0
    analytics_df["is_limit_up_proxy"] = analytics_df["pct_chg"] >= 9.8
    analytics_df["is_limit_down_proxy"] = analytics_df["pct_chg"] <= -9.8

    flow_df = normalize_moneyflow(moneyflow_df)
    if flow_df is not None:
        analytics_df = analytics_df.merge(flow_df, on=["ts_code", "trade_date"], how="left")
        if "net_mf_amount" in analytics_df.columns:
            analytics_df["net_mf_amount_100m"] = analytics_df["net_mf_amount"] / 10000

    write_dataframe(con, "dim_stock", stock_df)
    write_dataframe(con, "analytics_market_daily", analytics_df)
    save_processed_dataset(analytics_df, "analytics_market_daily")

    quality_report_df = build_quality_report(analytics_df, "analytics_market_daily", ["ts_code", "trade_date"])
    write_dataframe(con, "data_quality_report", quality_report_df)

    index_df = normalize_index_daily(index_daily_df)
    if index_df is not None:
        write_dataframe(con, "analytics_index_daily", index_df)
        save_processed_dataset(index_df, "analytics_index_daily")


def run(start_date: str | None, end_date: str | None, datasets: list[str], keep_going: bool, pause: float) -> None:
    client = TushareClient()
    con = connect()
    fetched_data = {}

    for dataset_name in datasets:
        dataset = DEFAULT_DATASETS[dataset_name]
        print(f"Fetching {dataset_name}...")
        try:
            df = fetch_dataset(client, dataset_name, start_date, end_date, pause)
        except Exception as exc:
            if dataset.get("required") and not keep_going:
                raise
            print(f"Skipped {dataset_name}: {exc}")
            continue

        print(f"{dataset_name}: {len(df)} rows")
        save_raw_dataset(df, dataset_name)
        write_dataframe(con, f"raw_{dataset_name}", df)
        fetched_data[dataset_name] = df

    if "stock_basic" in fetched_data and "daily" in fetched_data:
        build_market_table(
            con,
            fetched_data["stock_basic"],
            fetched_data["daily"],
            fetched_data.get("moneyflow"),
            fetched_data.get("index_daily"),
        )
        print("Built analytics_market_daily.")
    else:
        print("Skipped analytics_market_daily: stock_basic and daily are required.")

    con.close()
    snapshot_database()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Tushare A-share data into DuckDB.")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD, optional. Defaults to end-date minus rolling days.")
    parser.add_argument("--end-date", default=None, help="YYYYMMDD, optional. Defaults to today.")
    parser.add_argument("--days", type=int, default=180, help="Rolling window length when start-date is omitted.")
    parser.add_argument("--pause", type=float, default=0.15, help="Pause seconds between daily API requests.")
    parser.add_argument("--sample", action="store_true", help="Build a local sample database without Tushare token.")
    parser.add_argument("--sample-days", type=int, default=60, help="Business days to generate in sample mode.")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["stock_basic", "daily", "moneyflow", "limit_list_d", "index_daily"],
        choices=sorted(DEFAULT_DATASETS.keys()),
        help="Datasets to fetch.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail immediately when an optional dataset is unavailable.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.sample:
        run_sample(args.sample_days)
        raise SystemExit(0)
    if args.end_date is None:
        args.end_date = datetime.today().strftime("%Y%m%d")
    if args.start_date is None:
        end_dt = datetime.strptime(args.end_date, "%Y%m%d")
        args.start_date = (end_dt - timedelta(days=args.days)).strftime("%Y%m%d")
    print(f"Using date window: {args.start_date} - {args.end_date}")
    run(args.start_date, args.end_date, args.datasets, keep_going=not args.strict, pause=args.pause)
