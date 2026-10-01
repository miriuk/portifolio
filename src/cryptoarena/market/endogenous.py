from __future__ import annotations

import numpy as np

from .candle import Candle
from .orderbook import BookLevel, OrderBook
from .exchange import Fill, Order
from .synthetic import RegimeConfig, SyntheticMarket


class EndogenousMarket:
    """Market where agents trade against a shared order book.

    A hidden fundamental value per symbol follows the regime-switching
    process of SyntheticMarket. Noise traders quote a fresh book each step
    around a blend of the last traded price and the fundamental (so prices
    are anchored to reality but *moved by agent flow*): when agents buy
    aggressively they consume asks, print higher trades, and the next
    candle opens higher — their own behavior becomes part of the market.

    Implements both the market interface (next_candles) and the exchange
    interface (execute), since fills must feed back into price formation.
    """

    def __init__(
        self,
        symbols: dict[str, float],
        seed: int | None = None,
        config: RegimeConfig | None = None,
        fee_rate: float = 0.001,
        depth_levels: int = 12,
        liquidity_scale: float = 40_000.0,  # quote-ccy liquidity per side per step
        anchor_weight: float = 0.10,        # pull of fundamental on traded price
        start_timestamp: int = 1_700_000_000,
    ):
        self.fee_rate = fee_rate
        self.depth_levels = depth_levels
        self.liquidity_scale = liquidity_scale
        self.anchor_weight = anchor_weight
        self.rng = np.random.default_rng(seed)
        # fundamental value process (hidden from agents)
        self._fundamental = SyntheticMarket(symbols, seed=None if seed is None else seed + 1,
                                            config=config, start_timestamp=start_timestamp)
        self._fundamental.rng = np.random.default_rng(None if seed is None else seed + 1)
        self.start_timestamp = start_timestamp
        self._last_price = dict(symbols)
        self.books: dict[str, OrderBook] = {s: OrderBook() for s in symbols}
        self._t = 0
        self._step_trades: dict[str, list[tuple[float, float]]] = {s: [] for s in symbols}

    @property
    def symbols(self) -> list[str]:
        return list(self._last_price)

    @property
    def _regime(self) -> dict[str, str]:  # same attribute the episode runner reads
        return self._fundamental._regime

    def _quote_book(self, symbol: str, fundamental: float, vol: float) -> None:
        """Noise traders refresh liquidity around price/fundamental blend."""
        last = self._last_price[symbol]
        center = last * (1 - self.anchor_weight) + fundamental * self.anchor_weight
        spread = max(center * (0.0008 + vol * 0.5), center * 1e-4)
        asks, bids = [], []
        per_level_quote = self.liquidity_scale / self.depth_levels
        for i in range(1, self.depth_levels + 1):
            step_out = spread * (0.5 + 0.6 * (i - 1))
            size_mult = float(self.rng.lognormal(0, 0.4)) * (1 + 0.3 * i)
            ask_price = center + step_out
            bid_price = max(center - step_out, center * 0.01)
            asks.append(BookLevel(ask_price, per_level_quote * size_mult / ask_price))
            bids.append(BookLevel(bid_price, per_level_quote * size_mult / bid_price))
        self.books[symbol].set_liquidity(asks, bids)
        self._last_price[symbol] = center

    def next_candles(self) -> list[Candle]:
        """Close the current bar from realized trades, then re-quote books."""
        fundamentals = {c.symbol: c.close for c in self._fundamental.next_candles()}
        candles = []
        for symbol in self.symbols:
            trades = self._step_trades[symbol]
            open_price = self._last_price[symbol]
            prices = [p for p, _ in trades] or [open_price]
            agent_volume = sum(q for _, q in trades)
            vol = abs(np.log(fundamentals[symbol] / max(open_price, 1e-9))) + 0.002
            self._quote_book(symbol, fundamentals[symbol], float(vol))
            close_price = self._last_price[symbol]
            candles.append(Candle(
                symbol=symbol,
                timestamp=self.start_timestamp + self._t * 3600,
                open=round(open_price, 8),
                high=round(max(prices + [open_price, close_price]), 8),
                low=round(min(prices + [open_price, close_price]), 8),
                close=round(close_price, 8),
                volume=round(agent_volume + float(self.rng.lognormal(3, 0.5)), 4),
            ))
            self._step_trades[symbol] = []
        self._t += 1
        return candles

    # --- exchange interface --------------------------------------------------
    def execute(self, order: Order, candle: Candle) -> Fill:
        book = self.books[order.symbol]
        if order.side == "buy":
            budget = order.quote_amount * (1 - self.fee_rate)
            # walk asks until the budget is spent
            fills, spent, bought = [], 0.0, 0.0
            while budget - spent > 1e-9 and book.asks:
                level = book.asks[0]
                affordable = (budget - spent) / level.price
                traded = min(affordable, level.quantity)
                if traded <= 1e-12:
                    break
                fills.append((level.price, traded))
                spent += traded * level.price
                bought += traded
                level.quantity -= traded
                if level.quantity <= 1e-12:
                    book.asks.pop(0)
            if bought <= 0:  # book empty: fill tiny remainder at last price +5%
                price = self._last_price[order.symbol] * 1.05
                bought = budget / price
                fills = [(price, bought)]
                spent = budget
            vwap = spent / bought
            fee = order.quote_amount - spent  # = quote_amount * fee_rate (plus rounding)
        else:
            book_fills = book.take("sell", order.quote_amount)
            if not book_fills:
                price = self._last_price[order.symbol] * 0.95
                book_fills = [type("F", (), {"price": price, "quantity": order.quote_amount})()]
            bought = sum(f.quantity for f in book_fills)
            proceeds = sum(f.price * f.quantity for f in book_fills)
            vwap = proceeds / bought
            fee = proceeds * self.fee_rate
            fills = [(f.price, f.quantity) for f in book_fills]

        for price, qty in fills:
            self._step_trades[order.symbol].append((price, qty))
        self._last_price[order.symbol] = fills[-1][0]

        return Fill(
            agent_id=order.agent_id, symbol=order.symbol, side=order.side,
            quantity=bought, price=vwap, fee=fee,
            timestamp=candle.timestamp, reason=order.reason,
        )
