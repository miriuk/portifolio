from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookLevel:
    price: float
    quantity: float  # base units available at this price


@dataclass
class BookFill:
    price: float
    quantity: float


@dataclass
class OrderBook:
    """One symbol's resting liquidity: asks sorted ascending, bids descending.

    Liquidity is quoted by noise traders each step; agent market orders walk
    the levels, so a big order gets a worse average price AND leaves a
    thinner book for whoever trades next in the same step — real market
    impact, the mechanism replay/synthetic markets cannot give.
    """

    asks: list[BookLevel] = field(default_factory=list)
    bids: list[BookLevel] = field(default_factory=list)

    def set_liquidity(self, asks: list[BookLevel], bids: list[BookLevel]) -> None:
        self.asks = sorted(asks, key=lambda l: l.price)
        self.bids = sorted(bids, key=lambda l: -l.price)

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def mid(self) -> float | None:
        if self.best_ask is None or self.best_bid is None:
            return self.best_ask or self.best_bid
        return (self.best_ask + self.best_bid) / 2

    def depth(self, side: str) -> float:
        levels = self.asks if side == "buy" else self.bids
        return sum(l.quantity for l in levels)

    def take(self, side: str, quantity: float) -> list[BookFill]:
        """Consume liquidity: 'buy' walks the asks, 'sell' walks the bids.
        Returns the fills (possibly partial); consumed levels are removed."""
        levels = self.asks if side == "buy" else self.bids
        fills: list[BookFill] = []
        remaining = quantity
        while remaining > 1e-12 and levels:
            level = levels[0]
            traded = min(remaining, level.quantity)
            fills.append(BookFill(price=level.price, quantity=traded))
            level.quantity -= traded
            remaining -= traded
            if level.quantity <= 1e-12:
                levels.pop(0)
        return fills
