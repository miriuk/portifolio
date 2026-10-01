from __future__ import annotations

from dataclasses import dataclass

from ..market.exchange import Order
from .wallet import Wallet


@dataclass
class RiskLimits:
    max_position_pct: float = 0.35   # max fraction of equity in one symbol
    max_order_pct: float = 0.25      # max fraction of equity per order
    stop_loss_pct: float = 0.12      # force-exit a position down this much from basis
    max_drawdown_pct: float = 0.50   # kill switch: liquidate & halt below peak equity


class RiskManager:
    """Hard limits outside the agent's control — the seatbelt.

    Agents propose orders; the risk manager clips or vetoes them. Forced
    stop-loss exits are recorded so the learning loop can attribute the
    loss to the decision that opened the position.
    """

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.peak_equity: float = 0.0
        self.halted: bool = False

    def check_drawdown(self, equity: float) -> bool:
        """Update peak; returns True if the kill switch just tripped."""
        self.peak_equity = max(self.peak_equity, equity)
        if self.halted:
            return False
        if self.peak_equity > 0 and equity < self.peak_equity * (1 - self.limits.max_drawdown_pct):
            self.halted = True
            return True
        return False

    def stop_loss_exits(self, wallet: Wallet, prices: dict[str, float], agent_id: str) -> list[Order]:
        orders = []
        for symbol, qty in list(wallet.positions.items()):
            basis = wallet.cost_basis.get(symbol, 0.0)
            price = prices.get(symbol, 0.0)
            if basis <= 0:
                continue
            if qty > 0 and price < basis * (1 - self.limits.stop_loss_pct):
                orders.append(Order(
                    agent_id=agent_id, symbol=symbol, side="sell",
                    quote_amount=qty, reason="risk:stop_loss",
                ))
            elif qty < 0 and price > basis * (1 + self.limits.stop_loss_pct):
                orders.append(Order(                       # a short that ran against us: cover
                    agent_id=agent_id, symbol=symbol, side="buy",
                    quote_amount=0.0, reason="risk:stop_loss", base_qty=-qty,
                ))
        return orders

    def vet(self, order: Order, wallet: Wallet, prices: dict[str, float]) -> Order | None:
        """Clip an agent order to the limits; None if it must be dropped."""
        if self.halted:
            return None
        equity = wallet.equity(prices)
        if equity <= 0:
            return None
        held = wallet.positions.get(order.symbol, 0.0)
        if order.side == "buy" and order.base_qty:           # covering a short: never blocked
            if held >= 0:
                return None
            return Order(order.agent_id, order.symbol, "buy", 0.0, order.reason,
                         base_qty=min(order.base_qty, -held))
        if order.side == "buy":
            max_order = equity * self.limits.max_order_pct
            held_value = wallet.positions.get(order.symbol, 0.0) * prices.get(order.symbol, 0.0)
            room = equity * self.limits.max_position_pct - held_value
            amount = min(order.quote_amount, max_order, room, wallet.cash * 0.995)
            if amount < equity * 0.001:
                return None
            return Order(order.agent_id, order.symbol, "buy", amount, order.reason)
        if held > 0:
            return Order(order.agent_id, order.symbol, "sell", min(order.quote_amount, held),
                         order.reason)
        if not wallet.allow_short:
            return None
        price = prices.get(order.symbol, 0.0)                # a short: the same caps, on the short side
        if price <= 0:
            return None
        max_order = equity * self.limits.max_order_pct
        room = equity * self.limits.max_position_pct + held * price
        value = min(order.quote_amount * price, max_order, room)
        if value < equity * 0.001:
            return None
        return Order(order.agent_id, order.symbol, "sell", value / price, order.reason)
