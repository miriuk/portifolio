from __future__ import annotations

from dataclasses import dataclass, field

from ..market.exchange import Fill


@dataclass
class Wallet:
    """Paper wallet: quote-currency cash plus base-asset positions. A
    wallet that `allow_short` may sell what it does not hold: the position
    goes negative (a paper margin short, the proceeds sit in cash) and a
    buy covers it. `cost_basis` is the average entry price either way."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)   # symbol -> base qty (< 0: short)
    cost_basis: dict[str, float] = field(default_factory=dict)  # symbol -> avg entry price
    fees_paid: float = 0.0
    allow_short: bool = False

    def apply(self, fill: Fill) -> None:
        held = self.positions.get(fill.symbol, 0.0)
        prev_basis = self.cost_basis.get(fill.symbol, 0.0)
        if fill.side == "buy":
            spend = fill.quote_value + fill.fee
            if spend > self.cash + 1e-9:
                raise ValueError(f"insufficient cash: need {spend:.2f}, have {self.cash:.2f}")
            self.cash -= spend
            new_qty = held + fill.quantity
            if held < 0:                                   # covering a short
                if new_qty > 1e-12:                        # over-covered: the rest is a long
                    self.cost_basis[fill.symbol] = fill.price
            elif new_qty > 0:
                self.cost_basis[fill.symbol] = (
                    (held * prev_basis + fill.quantity * fill.price) / new_qty)
        else:
            if fill.quantity > held + 1e-9 and not self.allow_short:
                raise ValueError(f"insufficient {fill.symbol}: need {fill.quantity}, have {held}")
            new_qty = held - fill.quantity
            self.cash += fill.quote_value - fill.fee
            if new_qty < -1e-12:                           # opening or adding to a short
                short_held = max(-held, 0.0)
                added = fill.quantity - max(held, 0.0)
                self.cost_basis[fill.symbol] = (
                    fill.price if short_held <= 0 else
                    (short_held * prev_basis + added * fill.price) / (short_held + added))
        if abs(new_qty) <= 1e-12:
            self.positions.pop(fill.symbol, None)
            self.cost_basis.pop(fill.symbol, None)
        else:
            self.positions[fill.symbol] = new_qty
        self.fees_paid += fill.fee

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(
            qty * prices.get(sym, 0.0) for sym, qty in self.positions.items()
        )

    def short_notional(self, prices: dict[str, float]) -> float:
        return sum(-qty * prices.get(sym, 0.0) for sym, qty in self.positions.items() if qty < 0)

    def exposure(self, prices: dict[str, float]) -> float:
        """Gross exposure: everything at risk, long or short, over equity."""
        eq = self.equity(prices)
        if eq <= 0:
            return 0.0
        return sum(abs(qty) * prices.get(sym, 0.0) for sym, qty in self.positions.items()) / eq
