from pathlib import Path

import duckdb
import pandas as pd

from src.config import DB_PATH


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def write_dataframe(con: duckdb.DuckDBPyConnection, table_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("tmp_df", df)
    con.execute(f"create or replace table {table_name} as select * from tmp_df")
    con.unregister("tmp_df")


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    result = con.execute(
        """
        select count(*)
        from information_schema.tables
        where table_name = ?
        """,
        [table_name],
    ).fetchone()[0]
    return result > 0
