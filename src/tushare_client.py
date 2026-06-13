import os
import time
from typing import Any

import pandas as pd
import tushare as ts

from src.config import load_env


class TushareClient:
    """Small wrapper around Tushare Pro with token loading and retries."""

    def __init__(self) -> None:
        load_env()
        token = os.getenv("TUSHARE_TOKEN")
        if not token or token == "replace_with_your_tushare_token":
            raise ValueError("Please set TUSHARE_TOKEN in .env before fetching data.")

        self.pro = ts.pro_api(token)

    def query(self, api_name: str, retry: int = 3, pause: float = 1.0, **kwargs: Any) -> pd.DataFrame:
        last_error = None
        for attempt in range(1, retry + 1):
            try:
                return self.pro.query(api_name, **kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < retry:
                    time.sleep(pause * attempt)
        raise RuntimeError(f"Tushare query failed: {api_name}. Last error: {last_error}") from last_error
