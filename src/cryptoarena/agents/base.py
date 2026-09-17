from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

from ..market.candle import Candle
from ..market.exchange import Order
from ..portfolio.wallet import Wallet

HISTORY_LEN = 200


@dataclass
class MarketView:
    """What an agent is allowed to see each step."""

    candles: dict[str, Candle]                       # latest candle per symbol
    history: dict[str, deque[Candle]]                # rolling window per symbol
    prices: dict[str, float]
    step: int
    regimes: dict[str, str] = field(default_factory=dict)  # hidden by default


class TradingAgent(ABC):
    """observe -> decide -> (episode ends) -> learn."""

    def __init__(self, agent_id: str, starting_cash: float = 10_000.0):
        self.agent_id = agent_id
        self.starting_cash = starting_cash
        self.wallet = Wallet(cash=starting_cash)
        self.history: dict[str, deque[Candle]] = {}

    def observe(self, candles: list[Candle]) -> None:
        for c in candles:
            self.history.setdefault(c.symbol, deque(maxlen=HISTORY_LEN)).append(c)

    @abstractmethod
    def decide(self, view: MarketView) -> list[Order]:
        """Propose orders for this step (the risk manager may clip them)."""

    def learn(self, lessons: list[str]) -> None:
        """Hook called after reflection; override to adapt behavior."""

    # --- evolution interface -------------------------------------------------
    def get_params(self) -> dict | None:
        """Numeric tunable parameters, or None if not evolvable."""
        return None

    def set_params(self, params: dict) -> None:
        pass

    def reset_wallet(self) -> None:
        self.wallet = Wallet(cash=self.starting_cash)

    def clone(self, agent_id: str, starting_cash: float, rng=None,
              mutate: bool = False) -> "TradingAgent | None":
        """A fresh offspring: a faithful copy by default (parameters and the
        warmed-up indicator history), mutated only when asked. None if this
        agent type cannot reproduce."""
        return None

    def imitate(self, params: dict, rate: float) -> None:
        """Move own tunable parameters a fraction of the way towards `params`."""

    # --- indicator helpers ---------------------------------------------------
    def closes(self, symbol: str, n: int) -> list[float]:
        h = self.history.get(symbol)
        if not h:
            return []
        return [c.close for c in list(h)[-n:]]

    def sma(self, symbol: str, n: int) -> float | None:
        closes = self.closes(symbol, n)
        if len(closes) < n:
            return None
        return sum(closes) / n

    def momentum(self, symbol: str, n: int) -> float | None:
        closes = self.closes(symbol, n)
        if len(closes) < n:
            return None
        return (closes[-1] - closes[0]) / closes[0]

    def volatility(self, symbol: str, n: int = 24) -> float | None:
        closes = self.closes(symbol, n)
        if len(closes) < n:
            return None
        rets = [(b - a) / a for a, b in zip(closes, closes[1:])]
        mean = sum(rets) / len(rets)
        return (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
