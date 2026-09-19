"""Daily US stock bars, with the live feed's interface.

Two key-less public sources, both reachable from GitHub-hosted runners:
Stooq (one CSV per ticker, split-adjusted) and, when Stooq answers with
nothing — it rate-limits by IP — Yahoo Finance's chart endpoint. A bar's
timestamp is midnight UTC of its trading date, and a bar counts as
closed once its date is behind us, or on the same UTC day after 22:00
(the NYSE closes at 20:00 UTC and end-of-day rows land soon after).
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from .candle import Candle

STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}&i=d"
YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
             "?interval=1d&range={range}&includePrePost=false")
DEFAULT_STOCKS = {"SPY": "spy.us", "QQQ": "qqq.us", "AAPL": "aapl.us", "MSFT": "msft.us",
                  "NVDA": "nvda.us", "AMZN": "amzn.us"}
DAY = 86400
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_yahoo(ticker: str, range_: str = "10y") -> list[list[float]]:
    """Yahoo's chart JSON -> [timestamp(midnight UTC), o, h, l, c, v] rows. The
    `close` series is split-adjusted, which is what a backtest needs."""
    data = json.loads(_get(YAHOO_URL.format(ticker=ticker, range=range_)))
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return []
    stamps = result[0].get("timestamp") or []
    q = (result[0].get("indicators") or {}).get("quote", [{}])[0]
    rows = []
    for i, ts in enumerate(stamps):
        vals = [q.get(k, [None])[i] if i < len(q.get(k, [])) else None
                for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals[:4]):
            continue
        rows.append([int(ts) // DAY * DAY, *map(float, vals[:4]), float(vals[4] or 0.0)])
    rows.sort()
    return rows


def fetch_daily(ticker: str, min_rows: int = 100) -> list[list[float]]:
    """Stooq, then Yahoo when Stooq comes back (nearly) empty."""
    try:
        rows = fetch_stooq(ticker)
    except Exception:            # noqa: BLE001 — fall through to the second source
        rows = []
    if len(rows) >= min_rows:
        return rows
    yahoo = ticker.split(".")[0].upper()
    return fetch_yahoo(yahoo)


def fetch_stooq(ticker: str) -> list[list[float]]:
    """[timestamp, open, high, low, close, volume] rows, oldest first."""
    text = _get(STOOQ_URL.format(ticker=ticker)).decode("utf-8", "replace")
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


class StooqFeed:
    """Same shape as LiveFeed: history / aligned / next_candles, one bar a day."""

    exchange_id = "stooq"
    timeframe = "1d"
    seconds = DAY

    def __init__(self, symbols: dict[str, str] | None = None,
                 fetch: Callable[[str], list[list[float]]] | None = None,
                 now: Callable[[], float] | None = None, closed_after_hour: int = 22):
        self.symbols = symbols or dict(DEFAULT_STOCKS)
        self._fetch = fetch or fetch_daily
        self._now = now or time.time
        self.closed_after_hour = closed_after_hour

    def _closed(self, ts: int) -> bool:
        now = self._now()
        today = int(now // DAY) * DAY
        return ts < today or (ts == today and (now - today) // 3600 >= self.closed_after_hour)

    def history(self, limit: int = 250, since: int | None = None) -> dict[str, list[Candle]]:
        out: dict[str, list[Candle]] = {}
        for name, ticker in self.symbols.items():
            rows = [r for r in self._fetch(ticker) if self._closed(int(r[0]))
                    and (since is None or r[0] > since)]
            out[name] = [Candle(name, int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                                float(r[4]), float(r[5])) for r in rows[-limit:]]
        return out

    def aligned(self, limit: int = 250, since: int | None = None) -> list[list[Candle]]:
        per_symbol = self.history(limit, since)
        if not per_symbol:
            return []
        by_ts = [{c.timestamp: c for c in candles} for candles in per_symbol.values()]
        common = set(by_ts[0])
        for d in by_ts[1:]:
            common &= set(d)
        return [[d[ts] for d in by_ts] for ts in sorted(common)]

    def next_candles(self) -> list[Candle]:
        return [candles[-1] for candles in self.history(limit=1).values() if candles]
