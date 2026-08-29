from __future__ import annotations

from pathlib import Path

import pandas as pd

from .candle import Candle

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


class ReplayMarket:
    """Replays historical OHLCV CSVs, one candle per symbol per step.

    Each CSV must have columns: timestamp, open, high, low, close, volume.
    The symbol is taken from the file name (e.g. BTCUSDT.csv -> BTCUSDT).
    Use scripts/download_data.py (needs internet) to fetch real exchange data.
    """

    def __init__(self, csv_paths: list[str | Path]):
        self._frames: dict[str, pd.DataFrame] = {}
        for path in csv_paths:
            path = Path(path)
            df = pd.read_csv(path)
            missing = REQUIRED_COLUMNS - set(df.columns)
            if missing:
                raise ValueError(f"{path}: missing columns {sorted(missing)}")
            self._frames[path.stem] = df.reset_index(drop=True)
        self._cursor = 0
        self._length = min(len(df) for df in self._frames.values())

    @property
    def symbols(self) -> list[str]:
        return list(self._frames)

    def __len__(self) -> int:
        return self._length

    def next_candles(self) -> list[Candle]:
        if self._cursor >= self._length:
            raise StopIteration("replay data exhausted")
        candles = []
        for symbol, df in self._frames.items():
            row = df.iloc[self._cursor]
            candles.append(Candle(
                symbol=symbol, timestamp=int(row["timestamp"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]),
            ))
        self._cursor += 1
        return candles
