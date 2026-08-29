#!/usr/bin/env python3
"""Download historical OHLCV data via CCXT for use with ReplayMarket.

Needs internet access to the exchange (run on your own machine, not in a
sandboxed session). Example:

    pip install ccxt
    python scripts/download_data.py --exchange binance --symbol BTC/USDT \
        --timeframe 1h --days 365 --out data/BTCUSDT.csv
"""
from __future__ import annotations

import argparse
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    import ccxt
    import pandas as pd

    exchange = getattr(ccxt, args.exchange)()
    since = exchange.milliseconds() - args.days * 24 * 3600 * 1000
    rows = []
    while True:
        batch = exchange.fetch_ohlcv(args.symbol, args.timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + 1
        print(f"fetched {len(rows)} candles...", end="\r")
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"] // 1000  # ms -> s
    df.to_csv(args.out, index=False)
    print(f"\nwrote {len(df)} candles to {args.out}")


if __name__ == "__main__":
    main()
