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


class LiveFeed:
    """Polls real OHLCV candles via CCXT with the next_candles() interface."""

    def __init__(self, exchange_id: str = "binance",
                 symbols: dict[str, str] | None = None,  # arena name -> ccxt name
                 timeframe: str = "1h", client=None):
        self.symbols = symbols or {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT"}
        self.timeframe = timeframe
        if client is None:
            import ccxt
            client = getattr(ccxt, exchange_id)()
        self.client = client

    def next_candles(self) -> list[Candle]:
        candles = []
        for name, ccxt_symbol in self.symbols.items():
            ts, o, h, l, c, v = self.client.fetch_ohlcv(
                ccxt_symbol, self.timeframe, limit=1)[-1]
            candles.append(Candle(symbol=name, timestamp=int(ts // 1000),
                                  open=float(o), high=float(h), low=float(l),
                                  close=float(c), volume=float(v)))
        return candles


class LiveExchange:
    """Executes arena orders on a real exchange through CCXT — guarded.

    confirm is called as confirm(order, quote_value) -> bool for any order
    above the approval threshold; wire it to a Telegram prompt, a CLI input,
    or anything a human answers. No callback = those orders are refused.
    """

    def __init__(self, exchange_id: str = "binance",
                 api_key: str = "", api_secret: str = "",
                 symbols: dict[str, str] | None = None,
                 limits: LiveLimits | None = None,
                 dry_run: bool = True, testnet: bool = True,
                 confirm: Callable[[Order, float], bool] | None = None,
                 fee_rate: float = 0.001, client=None):
        self.symbols = symbols or {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT"}
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
