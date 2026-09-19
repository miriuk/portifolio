#!/usr/bin/env python3
"""Fetch hourly OHLCV history from Coinbase Exchange's public API (no key,
no CCXT, reachable from GitHub-hosted runners) into ReplayMarket CSVs.

    python scripts/fetch_history.py --days 400 --out data/
    # -> data/BTCUSD.csv, data/ETHUSD.csv, data/SOLUSD.csv

Columns: timestamp (unix seconds, candle open), open, high, low, close, volume.
Coinbase serves at most 300 candles per request, so a year is ~30 pages
per product; pages are fetched newest-first and written oldest-first.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.exchange.coinbase.com/products/{product}/candles"
PRODUCTS = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "SOLUSD": "SOL-USD"}


def fetch(product: str, days: int, granularity: int = 3600) -> list[list[float]]:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_limit = end - timedelta(days=days)
    span = timedelta(seconds=granularity * 300)
    rows: dict[int, list[float]] = {}
    cursor = end
    while cursor > start_limit:
        start = max(cursor - span, start_limit)
        url = (f"{API.format(product=product)}?granularity={granularity}"
               f"&start={start.isoformat()}&end={cursor.isoformat()}")
        req = urllib.request.Request(url, headers={"User-Agent": "cryptoarena/1.0"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    batch = json.loads(resp.read())
                break
            except Exception as exc:          # noqa: BLE001 — retry then give up
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        for t, lo, hi, o, c, v in batch:      # Coinbase order: time, low, high, open, close, volume
            rows[int(t)] = [int(t), float(o), float(hi), float(lo), float(c), float(v)]
        cursor = start
        time.sleep(0.25)
    return [rows[t] for t in sorted(rows)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--out", default="data")
    parser.add_argument("--products", default=",".join(f"{k}={v}" for k, v in PRODUCTS.items()),
                        help="comma list of ARENA=COINBASE pairs")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for pair in args.products.split(","):
        name, product = pair.split("=", 1)
        rows = fetch(product, args.days)
        path = out / f"{name}.csv"
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            w.writerows(rows)
        first = datetime.fromtimestamp(rows[0][0], tz=timezone.utc) if rows else None
        last = datetime.fromtimestamp(rows[-1][0], tz=timezone.utc) if rows else None
        print(f"{path}: {len(rows)} candles, {first:%Y-%m-%d} .. {last:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
