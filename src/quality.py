import pandas as pd


def _missing_rate(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or len(df) == 0:
        return float("nan")
    return float(df[column].isna().mean())


def build_quality_report(df: pd.DataFrame, table_name: str, key_columns: list[str] | None = None) -> pd.DataFrame:
    key_columns = key_columns or []
    report_rows = [
        {"table_name": table_name, "metric": "row_count", "value": float(len(df)), "detail": "表行数"},
        {"table_name": table_name, "metric": "column_count", "value": float(len(df.columns)), "detail": "字段数量"},
    ]

    if "trade_date" in df.columns and len(df) > 0:
        trade_dates = pd.to_datetime(df["trade_date"], errors="coerce")
        if trade_dates.notna().any():
            report_rows.extend(
                [
                    {
                        "table_name": table_name,
                        "metric": "min_trade_date",
                        "value": float(trade_dates.min().strftime("%Y%m%d")),
                        "detail": "最早交易日期",
                    },
                    {
                        "table_name": table_name,
                        "metric": "max_trade_date",
                        "value": float(trade_dates.max().strftime("%Y%m%d")),
                        "detail": "最新交易日期",
                    },
                    {
                        "table_name": table_name,
                        "metric": "trade_date_count",
                        "value": float(trade_dates.dt.normalize().nunique()),
                        "detail": "交易日期数量",
                    },
                ]
            )

    for column in ["ts_code", "trade_date", "name", "industry", "market", "close", "pct_chg", "amount_100m"]:
        if column in df.columns:
            report_rows.append(
                {
                    "table_name": table_name,
                    "metric": f"{column}_missing_rate",
                    "value": _missing_rate(df, column),
                    "detail": f"{column} 缺失率",
                }
            )

    valid_key_columns = [column for column in key_columns if column in df.columns]
    if valid_key_columns and len(df) > 0:
        duplicate_count = int(df.duplicated(valid_key_columns).sum())
        report_rows.append(
            {
                "table_name": table_name,
                "metric": "duplicate_key_count",
                "value": float(duplicate_count),
                "detail": "主键重复行数",
            }
        )

    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    report = pd.DataFrame(report_rows)
    report["generated_at"] = generated_at
    return report[["generated_at", "table_name", "metric", "value", "detail"]]
