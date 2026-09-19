"""Daily US stock and index bars, with the live feed's interface.

Three key-less sources, tried in order: Stooq (one CSV per ticker,
split-adjusted OHLC), Yahoo Finance's chart endpoint, and FRED's daily
index levels (close only). From a residential IP the first two work;
GitHub-hosted runners get a JavaScript wall from Stooq and 429s from
Yahoo, so there the floor runs on FRED — the S&P 500, Nasdaq 100 and
Dow as proxies for SPY, QQQ and DIA. Set CRYPTOARENA_DAILY_SOURCE=fred
to skip straight to FRED. A bar's timestamp is midnight UTC of its
trading date; it counts as closed once its date is behind us, or on the
same UTC day after 22:00 (the NYSE closes at 20:00 UTC).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from .candle import Candle

STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}&i=d"
YAHOO_URL = ("https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
             "?interval=1d&range={range}&includePrePost=false")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_PROXIES = {"SPY": "SP500", "QQQ": "NASDAQ100", "DIA": "DJIA"}   # index levels, close only
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{index}_History.csv"
CBOE_PROXIES = {"SPY": "SPX", "QQQ": "NDX", "DIA": "DJX", "IWM": "RUT"}   # OHLC index history
DEFAULT_STOCKS = {"SPY": "spy.us", "QQQ": "qqq.us", "DIA": "dia.us"}
EXTRA_STOCKS = {"AAPL": "aapl.us", "MSFT": "msft.us", "NVDA": "nvda.us", "AMZN": "amzn.us"}
DAY = 86400
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")


def _get(url: str, timeout: int = 30, attempts: int = 3) -> bytes:
    """GET with a browser user agent; throttling, server errors and timeouts
    are retried with a growing pause (shared runner IPs get throttled)."""
    import socket
    import urllib.error
    delay = 10
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


def parse_cboe(text: str) -> list[list[float]]:
    """Cboe's index history CSV (DATE,OPEN,HIGH,LOW,CLOSE, US dates) -> rows."""
    rows = []
    for line in text.splitlines()[1:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 5:
            continue
        day = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                day = datetime.strptime(parts[0], fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if day is None:
            continue
        try:
            o, h, lo, c = (float(x) for x in parts[1:5])
        except ValueError:
            continue
        if c <= 0:
            continue
        rows.append([int(day.timestamp()), o or c, h or c, lo or c, c, 0.0])
    rows.sort()
    return rows


def fetch_cboe(index: str) -> list[list[float]]:
    """Daily OHLC of an index from Cboe's public CDN (SPX, NDX, DJX, RUT…)."""
    return parse_cboe(_get(CBOE_URL.format(index=index), timeout=60).decode("utf-8", "replace"))


_yahoo_opener = None


def _yahoo_get(url: str, attempts: int = 2) -> bytes:
    """Yahoo wants a session cookie and a 'crumb' before it serves data to
    an unfamiliar IP; without them shared runners get 429s. Same dance the
    usual libraries do, with a growing pause on throttling."""
    global _yahoo_opener
    import http.cookiejar
    import urllib.error
    delay = 5
    for attempt in range(attempts):
        try:
            if _yahoo_opener is None:
                jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                opener.addheaders = [("User-Agent", _UA), ("Accept", "*/*")]
                try:
                    opener.open("https://fc.yahoo.com", timeout=30).read()
                except urllib.error.HTTPError:
                    pass                          # 404 is fine: the cookie is set anyway
                crumb = opener.open("https://query2.finance.yahoo.com/v1/test/getcrumb",
                                    timeout=30).read().decode().strip()
                _yahoo_opener = (opener, crumb)
            opener, crumb = _yahoo_opener
            sep = "&" if "?" in url else "?"
            return opener.open(f"{url}{sep}crumb={urllib.parse.quote(crumb)}", timeout=30).read()
        except urllib.error.HTTPError as exc:
            _yahoo_opener = None                  # a fresh session next time
            if exc.code not in (401, 403, 429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def fetch_fred(series: str) -> list[list[float]]:
    """FRED's daily index levels (close only): a bar with o = h = l = c."""
    text = _get(FRED_URL.format(series=series), timeout=120).decode("utf-8", "replace")
    rows = []
    for line in text.splitlines()[1:]:
        date, _, value = line.partition(",")
        if value.strip() in ("", "."):
            continue
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            close = float(value)
        except ValueError:
            continue
        rows.append([int(day.timestamp()), close, close, close, close, 0.0])
    rows.sort()
    return rows


def fetch_yahoo(ticker: str, range_: str = "10y") -> list[list[float]]:
    """Yahoo's chart JSON -> [timestamp(midnight UTC), o, h, l, c, v] rows. The
    `close` series is split-adjusted, which is what a backtest needs."""
    data = json.loads(_yahoo_get(YAHOO_URL.format(ticker=ticker, range=range_)))
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


def fetch_daily(ticker: str, min_rows: int = 100, verbose: bool = True) -> list[list[float]]:
    """Stooq, then Yahoo, then FRED (index proxies only); or FRED straight
    away when CRYPTOARENA_DAILY_SOURCE=fred."""
    import os
    yahoo = ticker.split(".")[0].upper()
    if os.environ.get("CRYPTOARENA_DAILY_SOURCE", "").lower() in ("fred", "index"):
        return _fetch_index_proxy(yahoo, verbose)
    try:
        rows = fetch_stooq(ticker, verbose=verbose)
    except Exception as exc:     # noqa: BLE001 — fall through to the second source
        if verbose:
            print(f"stooq {ticker}: {exc}", flush=True)
        rows = []
    if len(rows) >= min_rows:
        return rows
    time.sleep(2)                # be a polite guest on the second source
    try:
        rows = fetch_yahoo(yahoo)
    except Exception as exc:     # noqa: BLE001 — last resort below
        if verbose:
            print(f"yahoo {yahoo}: {exc}", flush=True)
        rows = []
    if len(rows) >= min_rows:
        return rows
    return _fetch_index_proxy(yahoo, verbose) or rows


def _fetch_index_proxy(ticker: str, verbose: bool = True) -> list[list[float]]:
    """The index behind an ETF, from Cboe (OHLC) or FRED (close only)."""
    if ticker in CBOE_PROXIES:
        try:
            rows = fetch_cboe(CBOE_PROXIES[ticker])
            if rows:
                if verbose:
                    print(f"{ticker}: Cboe {CBOE_PROXIES[ticker]} history, {len(rows)} bars", flush=True)
                return rows
        except Exception as exc:     # noqa: BLE001 — try FRED next
            if verbose:
                print(f"cboe {CBOE_PROXIES[ticker]}: {exc}", flush=True)
    if ticker in FRED_PROXIES:
        try:
            rows = fetch_fred(FRED_PROXIES[ticker])
            if verbose:
                print(f"{ticker}: FRED {FRED_PROXIES[ticker]} levels, {len(rows)} bars", flush=True)
            return rows
        except Exception as exc:     # noqa: BLE001
            if verbose:
                print(f"fred {FRED_PROXIES[ticker]}: {exc}", flush=True)
    if verbose:
        print(f"{ticker}: no index proxy available; skipped", flush=True)
    return []


def fetch_stooq(ticker: str, verbose: bool = False) -> list[list[float]]:
    """[timestamp, open, high, low, close, volume] rows, oldest first."""
    text = _get(STOOQ_URL.format(ticker=ticker)).decode("utf-8", "replace")
    if verbose and not text.lstrip().startswith("Date"):
        print(f"stooq {ticker}: unexpected answer: {text[:160]!r}", flush=True)
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
            try:
                fetched = self._fetch(ticker)
            except Exception as exc:     # noqa: BLE001 — one bad ticker must not stop the bar
                print(f"[feed] {ticker}: {exc}; skipping this fetch", flush=True)
                continue
            if not fetched:
                continue
            rows = [r for r in fetched if self._closed(int(r[0]))
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
