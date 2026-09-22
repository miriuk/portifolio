"""Live trading layer: same agent interface, real exchange underneath.

Safety model (each layer is independent; disabling one leaves the rest):

1. dry_run=True by default    -> orders are logged and simulated, never sent
2. testnet=True by default    -> real API calls go to the exchange sandbox
3. per-order hard cap         -> any order above max_order_quote is CLIPPED
4. daily spend hard cap       -> buys stop when the day's quote spend hits
                                 max_daily_quote
5. human approval threshold   -> orders above approve_above_quote require a
                                 confirm callback; with no callback they are
                                 REFUSED, never sent

Recommended exchange-side setup (cannot be enforced from code — do it in the
exchange UI): API keys with trade permission ONLY (no withdrawal), IP
restriction, and a sub-account holding only what you can afford to lose.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .candle import Candle
from .exchange import Fill, Order


@dataclass
class LiveLimits:
    max_order_quote: float = 50.0      # hard clip per order, quote currency
    max_daily_quote: float = 200.0     # hard stop on total buys per UTC day
    approve_above_quote: float = 25.0  # orders above this need human approval


TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                     "1h": 3600, "4h": 14400, "1d": 86400}

# Arena symbol -> CCXT symbol, per exchange. Kraken is the default because it
# serves public OHLCV worldwide without an account (Binance refuses US
# addresses, which is where GitHub-hosted runners live).
DEFAULT_SYMBOLS: dict[str, dict[str, str]] = {
    "kraken": {"BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD", "SOLUSD": "SOL/USD"},
    "binance": {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT", "SOLUSDT": "SOL/USDT"},
    "coinbase": {"BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD", "SOLUSD": "SOL/USD"},
}


# The wider universe: majors quoted in USD on both Kraken (the live feed)
# and Coinbase (the backtest tape), so a backtest and the live colony see
# the same names. CoinMarketCap's full list is thousands of coins, most
# without a liquid USD pair anywhere; these are the ones with real markets.
MAJORS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "LTC", "BCH",
          "UNI", "ATOM", "XLM", "ETC", "NEAR", "APT", "ARB", "OP", "FIL", "AAVE", "ALGO",
          "SUI", "INJ"]


def default_symbols(exchange_id: str) -> dict[str, str]:
    return dict(DEFAULT_SYMBOLS.get(exchange_id, DEFAULT_SYMBOLS["kraken"]))


def majors_symbols(exchange_id: str = "kraken", quote: str | None = None) -> dict[str, str]:
    """Arena name -> CCXT symbol for the majors on the given exchange."""
    quote = quote or ("USDT" if exchange_id == "binance" else "USD")
    return {f"{coin}{quote}": f"{coin}/{quote}" for coin in MAJORS}


class LiveFeed:
    """Real OHLCV candles via CCXT, with the next_candles() interface.

    `closed_only` (the default) hides the candle still being formed: the
    agents see a bar only once it has closed, exactly like the simulated
    market, so nothing they learn depends on the second they were polled.
    """

    def __init__(self, exchange_id: str = "kraken",
                 symbols: dict[str, str] | None = None,  # arena name -> ccxt name
                 timeframe: str = "1h", client=None, closed_only: bool = True,
                 now: Callable[[], float] | None = None):
        self.exchange_id = exchange_id
        self.symbols = symbols or default_symbols(exchange_id)
        self.timeframe = timeframe
        self.closed_only = closed_only
        self._now = now or time.time
        if client is None:
            import ccxt
            client = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.client = client

    @property
    def seconds(self) -> int:
        return TIMEFRAME_SECONDS[self.timeframe]

    def _fetch(self, ccxt_symbol: str, since: int | None, limit: int) -> list:
        since_ms = None if since is None else int(since) * 1000
        rows = self.client.fetch_ohlcv(ccxt_symbol, self.timeframe, since=since_ms,
                                       limit=limit)
        if self.closed_only:
            cutoff = self._now() - self.seconds
            rows = [r for r in rows if r[0] // 1000 <= cutoff]
        return rows

    def history(self, limit: int = 200, since: int | None = None) -> dict[str, list[Candle]]:
        """Closed candles per arena symbol, oldest first — `since` is an
        exclusive unix-seconds lower bound on the candle's open time."""
        out: dict[str, list[Candle]] = {}
        for name, ccxt_symbol in self.symbols.items():
            try:
                rows = self._fetch(ccxt_symbol, since, limit)
            except Exception as exc:     # noqa: BLE001 — one bad pair must not stop the bar
                print(f"[feed] {ccxt_symbol}: {exc}; skipping this fetch")
                continue
            out[name] = [Candle(symbol=name, timestamp=int(r[0] // 1000), open=float(r[1]),
                                high=float(r[2]), low=float(r[3]), close=float(r[4]),
                                volume=float(r[5]))
                         for r in rows if since is None or r[0] // 1000 > since]
        return out

    def aligned(self, limit: int = 200, since: int | None = None) -> list[list[Candle]]:
        """History regrouped by timestamp: one list of candles (one per
        symbol) per bar, only for bars every symbol has, oldest first."""
        per_symbol = self.history(limit, since)
        if not per_symbol:
            return []
        by_ts = [{c.timestamp: c for c in candles} for candles in per_symbol.values()]
        common = set(by_ts[0])
        for d in by_ts[1:]:
            common &= set(d)
        return [[d[ts] for d in by_ts] for ts in sorted(common)]

    def next_candles(self) -> list[Candle]:
        """The latest (closed) bar per symbol."""
        return [candles[-1] for candles in self.history(limit=2).values() if candles]

    def min_costs(self, prices: dict[str, float]) -> dict[str, float]:
        """The smallest order the exchange accepts per arena symbol, in
        quote currency at the given prices: the market's minimum cost, or
        its minimum amount times the price. Real money starts here — a
        paper order below this line could never have been sent."""
        try:
            markets = self.client.load_markets()
        except Exception as exc:     # noqa: BLE001 — readiness is informative, never fatal
            print(f"[feed] load_markets: {exc}")
            return {}
        out: dict[str, float] = {}
        for name, ccxt_symbol in self.symbols.items():
            m = markets.get(ccxt_symbol) or {}
            limits = m.get("limits") or {}
            cost_min = (limits.get("cost") or {}).get("min")
            amount_min = (limits.get("amount") or {}).get("min")
            price = prices.get(name)
            floor = 0.0
            if cost_min:
                floor = float(cost_min)
            if amount_min and price:
                floor = max(floor, float(amount_min) * price)
            if floor:
                out[name] = round(floor, 4)
        return out


class LiveExchange:
    """Executes arena orders on a real exchange through CCXT — guarded.

    confirm is called as confirm(order, quote_value) -> bool for any order
    above the approval threshold; wire it to a Telegram prompt, a CLI input,
    or anything a human answers. No callback = those orders are refused.
    """

    def __init__(self, exchange_id: str = "kraken",
                 api_key: str = "", api_secret: str = "",
                 symbols: dict[str, str] | None = None,
                 limits: LiveLimits | None = None,
                 dry_run: bool = True, testnet: bool = True,
                 confirm: Callable[[Order, float], bool] | None = None,
                 fee_rate: float = 0.001, client=None):
        self.symbols = symbols or default_symbols(exchange_id)
        self.limits = limits or LiveLimits()
        self.dry_run = dry_run
        self.testnet = testnet
        self.confirm = confirm
        self.fee_rate = fee_rate
        self._spent_today = 0.0
        self._spend_day: int | None = None
        if client is None and not dry_run:
            import ccxt
            client = getattr(ccxt, exchange_id)({
                "apiKey": api_key, "secret": api_secret,
            })
        self.client = client
        if self.client is not None and testnet:
            self.client.set_sandbox_mode(True)

    def _daily_spend_room(self, now: float | None = None) -> float:
        day = int((now if now is not None else time.time()) // 86400)
        if day != self._spend_day:
            self._spend_day = day
            self._spent_today = 0.0
        return self.limits.max_daily_quote - self._spent_today

    def execute(self, order: Order, candle: Candle) -> Fill | None:
        """Returns the Fill, or None when a guard refused the order."""
        price = candle.close
        quote_value = order.quote_amount if order.side == "buy" \
            else order.quote_amount * price

        # guard 3: per-order hard cap (clip, don't refuse)
        if quote_value > self.limits.max_order_quote:
            scale = self.limits.max_order_quote / quote_value
            order = Order(order.agent_id, order.symbol, order.side,
                          order.quote_amount * scale, order.reason)
            quote_value = self.limits.max_order_quote

        # guard 4: daily buy cap
        if order.side == "buy":
            room = self._daily_spend_room()
            if room <= 0:
                print(f"[live] REFUSED {order.side} {order.symbol}: daily cap reached")
                return None
            if quote_value > room:
                order = Order(order.agent_id, order.symbol, order.side,
                              room, order.reason)
                quote_value = room

        # guard 5: human approval above threshold
        if quote_value > self.limits.approve_above_quote:
            if self.confirm is None or not self.confirm(order, quote_value):
                print(f"[live] REFUSED {order.side} {order.symbol} "
                      f"{quote_value:.2f}: needs human approval")
                return None

        if order.side == "buy":
            quantity = quote_value * (1 - self.fee_rate) / price
            fee = quote_value * self.fee_rate
        else:
            quantity = order.quote_amount
            fee = quantity * price * self.fee_rate

        # guard 1: dry run — log and simulate, never send
        if self.dry_run:
            print(f"[live:DRY-RUN] {order.side} {order.symbol} "
                  f"qty={quantity:.8f} @ ~{price:.2f} ({order.reason})")
        else:
            ccxt_symbol = self.symbols[order.symbol]
            if order.side == "buy":
                resp = self.client.create_market_buy_order(ccxt_symbol, quantity)
            else:
                resp = self.client.create_market_sell_order(ccxt_symbol, quantity)
            price = float(resp.get("average") or resp.get("price") or price)
            quantity = float(resp.get("filled") or quantity)

        if order.side == "buy":
            self._spent_today += quote_value

        return Fill(agent_id=order.agent_id, symbol=order.symbol,
                    side=order.side, quantity=quantity, price=price, fee=fee,
                    timestamp=candle.timestamp, reason=order.reason)
