from __future__ import annotations

from dataclasses import dataclass, field

from ..market.exchange import Fill


@dataclass
class Wallet:
    """Paper wallet: quote-currency cash plus base-asset positions."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)   # symbol -> base qty
    cost_basis: dict[str, float] = field(default_factory=dict)  # symbol -> avg entry price
    fees_paid: float = 0.0

    def apply(self, fill: Fill) -> None:
        if fill.side == "buy":
            spend = fill.quote_value + fill.fee
            if spend > self.cash + 1e-9:
                raise ValueError(f"insufficient cash: need {spend:.2f}, have {self.cash:.2f}")
            self.cash -= spend
            held = self.positions.get(fill.symbol, 0.0)
            prev_basis = self.cost_basis.get(fill.symbol, 0.0)
            new_qty = held + fill.quantity
            self.cost_basis[fill.symbol] = (
                (held * prev_basis + fill.quantity * fill.price) / new_qty if new_qty > 0 else 0.0
            )
            self.positions[fill.symbol] = new_qty
        else:
            held = self.positions.get(fill.symbol, 0.0)
            if fill.quantity > held + 1e-9:
                raise ValueError(f"insufficient {fill.symbol}: need {fill.quantity}, have {held}")
            self.positions[fill.symbol] = held - fill.quantity
            self.cash += fill.quote_value - fill.fee
            if self.positions[fill.symbol] <= 1e-12:
                self.positions.pop(fill.symbol, None)
                self.cost_basis.pop(fill.symbol, None)
        self.fees_paid += fill.fee

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(
            qty * prices.get(sym, 0.0) for sym, qty in self.positions.items()
        )

    def exposure(self, prices: dict[str, float]) -> float:
        eq = self.equity(prices)
        if eq <= 0:
            return 0.0
        return 1.0 - self.cash / eq
