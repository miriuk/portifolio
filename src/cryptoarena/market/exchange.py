from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .candle import Candle


@dataclass
class Order:
    agent_id: str
    symbol: str
    side: str          # "buy" | "sell"
    quote_amount: float  # buy: quote currency to spend; sell: base quantity to sell
    reason: str = ""


@dataclass
class Fill:
    agent_id: str
    symbol: str
    side: str
    quantity: float      # base asset filled
    price: float         # effective price incl. slippage
    fee: float           # quote currency
    timestamp: int
    reason: str = ""

    @property
    def quote_value(self) -> float:
        return self.quantity * self.price


class SimulatedExchange:
    """Fills market orders against the current candle with fees and slippage.

    Slippage grows with order size relative to bar volume, so oversized
    orders get punished — one of the mistakes agents must learn to avoid.
    """

    def __init__(self, fee_rate: float = 0.001, slippage_base: float = 0.0005,
                 seed: int | None = None):
        self.fee_rate = fee_rate
        self.slippage_base = slippage_base
        self.rng = np.random.default_rng(seed)

    def execute(self, order: Order, candle: Candle) -> Fill:
        mid = candle.close
        bar_quote_volume = max(candle.volume * mid, 1e-9)
        order_quote = order.quote_amount if order.side == "buy" else order.quote_amount * mid
        impact = self.slippage_base * (1 + 20 * min(order_quote / bar_quote_volume, 1.0))
        noise = abs(self.rng.standard_normal()) * self.slippage_base
        slip = impact + noise
        price = mid * (1 + slip) if order.side == "buy" else mid * (1 - slip)

        if order.side == "buy":
            fee = order.quote_amount * self.fee_rate
            quantity = (order.quote_amount - fee) / price
        else:
            quantity = order.quote_amount  # base units
            fee = quantity * price * self.fee_rate

        return Fill(
            agent_id=order.agent_id, symbol=order.symbol, side=order.side,
            quantity=quantity, price=price, fee=fee,
            timestamp=candle.timestamp, reason=order.reason,
        )
