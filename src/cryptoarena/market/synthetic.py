from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .candle import Candle

# Per-regime (annualized drift, annualized volatility, transition stickiness)
DEFAULT_REGIMES = {
    "bull": (1.2, 0.45, 0.990),
    "bear": (-0.9, 0.70, 0.985),
    "chop": (0.0, 0.30, 0.992),
    "mania": (3.5, 1.10, 0.970),
    "crash": (-4.0, 1.60, 0.950),
}

BARS_PER_YEAR = 365 * 24  # hourly bars


@dataclass
class RegimeConfig:
    regimes: dict[str, tuple[float, float, float]] = field(
        default_factory=lambda: dict(DEFAULT_REGIMES)
    )
    jump_prob: float = 0.004        # chance per bar of a news shock
    jump_scale: float = 0.06        # typical shock magnitude (log-return)
    start_regime: str = "chop"


class SyntheticMarket:
    """Regime-switching geometric Brownian motion with jump shocks.

    Produces hourly OHLCV candles for several symbols. Regimes (bull, bear,
    chop, mania, crash) switch stochastically per symbol, so agents face
    changing conditions they must adapt to — the point of the arena.
    """

    def __init__(
        self,
        symbols: dict[str, float],  # symbol -> starting price
        seed: int | None = None,
        config: RegimeConfig | None = None,
        start_timestamp: int = 1_700_000_000,
    ):
        self.config = config or RegimeConfig()
        self.rng = np.random.default_rng(seed)
        self.start_timestamp = start_timestamp
        self._prices = dict(symbols)
        self._regime = {s: self.config.start_regime for s in symbols}
        self._t = 0
        self.regime_history: dict[str, list[str]] = {s: [] for s in symbols}

    @property
    def symbols(self) -> list[str]:
        return list(self._prices)

    def _step_regime(self, symbol: str) -> str:
        current = self._regime[symbol]
        _, _, stickiness = self.config.regimes[current]
        if self.rng.random() > stickiness:
            names = list(self.config.regimes)
            # mania decays into crash more often than into calm regimes
            if current == "mania" and self.rng.random() < 0.5:
                nxt = "crash"
            else:
                nxt = names[self.rng.integers(len(names))]
            self._regime[symbol] = nxt
        return self._regime[symbol]

    def next_candles(self) -> list[Candle]:
        """Advance one hour and return a candle per symbol."""
        candles = []
        dt = 1.0 / BARS_PER_YEAR
        for symbol, price in self._prices.items():
            regime = self._step_regime(symbol)
            self.regime_history[symbol].append(regime)
            mu, sigma, _ = self.config.regimes[regime]
            log_ret = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * self.rng.standard_normal()
            if self.rng.random() < self.config.jump_prob:
                log_ret += self.rng.standard_normal() * self.config.jump_scale
            close = price * float(np.exp(log_ret))
            intrabar_vol = abs(log_ret) + sigma * np.sqrt(dt) * 0.5
            high = max(price, close) * (1 + abs(self.rng.standard_normal()) * intrabar_vol * 0.5)
            low = min(price, close) * (1 - abs(self.rng.standard_normal()) * intrabar_vol * 0.5)
            volume = float(1000 * (1 + 10 * abs(log_ret)) * self.rng.lognormal(0, 0.3))
            candles.append(Candle(
                symbol=symbol,
                timestamp=self.start_timestamp + self._t * 3600,
                open=round(price, 8), high=round(high, 8),
                low=round(low, 8), close=round(close, 8),
                volume=round(volume, 2),
            ))
            self._prices[symbol] = close
        self._t += 1
        return candles
