#!/usr/bin/env python3
"""Fetch OHLCV history from public, key-less APIs that GitHub-hosted
runners can reach, into ReplayMarket CSVs.

    python scripts/fetch_history.py --days 400 --out data/
    # -> data/BTCUSD.csv, data/ETHUSD.csv, data/SOLUSD.csv   (Coinbase, hourly)

    python scripts/fetch_history.py --source stooq --out data/stocks
    # -> data/stocks/SPY.csv, QQQ.csv, ...                    (Stooq, daily)

Columns: timestamp (unix seconds, candle open), open, high, low, close, volume.
Coinbase serves at most 300 candles per request, so a year is ~30 pages
per product; pages are fetched newest-first and written oldest-first.
Stooq serves a ticker's whole daily history in one CSV; a daily bar's
timestamp is midnight UTC of its date.
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
STOOQ = "https://stooq.com/q/d/l/?s={ticker}&i=d"
STOCKS = {"SPY": "spy.us", "QQQ": "qqq.us", "AAPL": "aapl.us", "MSFT": "msft.us",
          "NVDA": "nvda.us", "AMZN": "amzn.us"}


def fetch_stooq(ticker: str, days: int | None = None) -> list[list[float]]:
    """Daily bars, oldest first; `days` keeps only the most recent ones.
    Stooq rate-limits by IP and then answers with a stub, so the package's
    fetch_daily (Stooq, then Yahoo Finance) is used when it is installed."""
    try:
        from cryptoarena.market.stocks import fetch_daily
        rows = fetch_daily(ticker)
    except ImportError:
        rows = _fetch_stooq_raw(ticker)
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        rows = [r for r in rows if r[0] >= cutoff]
    return rows


def _fetch_stooq_raw(ticker: str) -> list[list[float]]:
    req = urllib.request.Request(STOOQ.format(ticker=ticker),
                                 headers={"User-Agent": "cryptoarena/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", "replace")
    if not text.lstrip().startswith("Date"):
        print(f"stooq {ticker}: unexpected answer: {text[:120]!r}")
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 6 or not parts[0][:4].isdigit():
            continue
        try:
            day = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            o, h, lo, c = (float(x) for x in parts[1:5])
            v = float(parts[5]) if parts[5] else 0.0
        except ValueError:
            continue
        rows.append([int(day.timestamp()), o, h, lo, c, v])
    rows.sort()
    return rows


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
    parser.add_argument("--source", choices=["coinbase", "stooq"], default="coinbase")
    parser.add_argument("--products", default=None,
                        help="comma list of ARENA=SOURCE pairs (e.g. SPY=spy.us)")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    defaults = STOCKS if args.source == "stooq" else PRODUCTS
    products = args.products or ",".join(f"{k}={v}" for k, v in defaults.items())
    for pair in products.split(","):
        name, product = pair.split("=", 1)
        rows = fetch_stooq(product, args.days) if args.source == "stooq" \
            else fetch(product, args.days)
        if not rows:
            raise SystemExit(f"{name}: no rows from {args.source} for {product}")
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
