from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    """One OHLCV bar of a single symbol."""

    symbol: str
    timestamp: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def range_pct(self) -> float:
        return (self.high - self.low) / self.low if self.low > 0 else 0.0

    @property
    def return_pct(self) -> float:
        return (self.close - self.open) / self.open if self.open > 0 else 0.0
