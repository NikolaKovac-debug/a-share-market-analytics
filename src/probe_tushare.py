import argparse

from src.tushare_client import TushareClient


DATE_REQUIRED_APIS = {
    "daily",
    "moneyflow",
    "limit_list_d",
    "limit_list",
    "stk_limit",
}


def probe(api_names: list[str], start_date: str | None, end_date: str | None) -> None:
    client = TushareClient()
    for api_name in api_names:
        try:
            params = {}
            if api_name in DATE_REQUIRED_APIS:
                if start_date:
                    params["start_date"] = start_date
                if end_date:
                    params["end_date"] = end_date

            df = client.query(api_name, **params)
            print(f"[OK] {api_name}: {len(df)} rows")
            print(f"     columns: {', '.join(df.columns[:12])}")
        except Exception as exc:
            print(f"[FAIL] {api_name}: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Tushare API names.")
    parser.add_argument("api_names", nargs="+", help="Tushare API names to test.")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD, optional")
    parser.add_argument("--end-date", default=None, help="YYYYMMDD, optional")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    probe(args.api_names, args.start_date, args.end_date)
