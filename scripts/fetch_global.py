#!/usr/bin/env python3
"""Daily bars of the world universe (market/universe.py) from Nasdaq's
public API, `--years` back, into one CSV per ticker:

    python scripts/fetch_global.py --years 10 --out data/global
    # -> data/global/etf/SPY.csv, EWU.csv, …   data/global/stocks/AAPL.csv, …

Nasdaq's bars are split-adjusted, not dividend-adjusted: a holder's
return is understated by the dividend yield, the same for every strategy.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptoarena.market.stocks import NASDAQ_URL, _get, parse_nasdaq
from cryptoarena.market.universe import (LARGE_CAPS, WORLD_ETFS, adjust_corporate_actions,
                                         asset_class)


def fetch(ticker: str, years: int) -> list[list[float]]:
    fromdate = (datetime.now(timezone.utc) - timedelta(days=int(365.25 * years))).strftime("%Y-%m-%d")
    url = NASDAQ_URL.format(ticker=ticker, assetclass=asset_class(ticker), fromdate=fromdate)
    return adjust_corporate_actions(ticker, parse_nasdaq(json.loads(_get(url, timeout=60))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--out", default="data/global")
    ap.add_argument("--only", default=None, help="comma list of tickers (default: all)")
    args = ap.parse_args()
    tickers = args.only.split(",") if args.only else [*WORLD_ETFS, *LARGE_CAPS]
    missing = []
    for i, t in enumerate(tickers):
        if i:
            time.sleep(1.5)                       # a polite pace for a shared runner IP
        try:
            rows = fetch(t, args.years)
        except Exception as exc:                  # noqa: BLE001 — one ticker is not fatal
            print(f"{t}: {exc}", flush=True)
            missing.append(t)
            continue
        if len(rows) < 250:
            print(f"{t}: only {len(rows)} bars; skipped", flush=True)
            missing.append(t)
            continue
        kind = "etf" if asset_class(t) == "etf" else "stocks"
        path = Path(args.out) / kind / f"{t}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            w.writerows(rows)
        first, last = (datetime.fromtimestamp(rows[k][0], tz=timezone.utc) for k in (0, -1))
        print(f"{path}: {len(rows)} bars, {first:%Y-%m-%d} .. {last:%Y-%m-%d}", flush=True)
    print(f"done: {len(tickers) - len(missing)} of {len(tickers)}"
          + (f"; missing {', '.join(missing)}" if missing else ""), flush=True)


if __name__ == "__main__":
    main()
