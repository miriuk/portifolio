"""Hold with a trend exit: the investor's baseline the colony has to beat.

No colony, no survival rules: hold coins, and step aside into cash while
the trend is down. Once a day (the bar that closes at 00:00 UTC) every
coin in the universe is checked:

- signal on and not held  -> buy it with equity / len(universe)
- signal off and held     -> sell it all
- otherwise               -> let it drift (no rebalancing churn)

Signals, each over `days` of hourly closes:

- coin:   the coin itself is up over the lookback
- market: BTC is up over the lookback (everything in, or everything out)
- both:   the coin is up and BTC is up
- btc:    BTC only, while BTC is up

Fees are charged on every buy and sell. The signal uses the bar's close
and fills at that close; on an hourly crypto tape the next open is the
same price to within noise.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import window_symbols

KINDS = ("coin", "market", "both", "btc")


@dataclass
class Tape:
    symbols: list[str]
    ts: np.ndarray            # T unix seconds
    close: np.ndarray         # T x N, NaN before a coin is listed
    open: np.ndarray

    @classmethod
    def from_frames(cls, tape: dict[str, pd.DataFrame]) -> "Tape":
        syms = list(tape)
        ts = tape[syms[0]]["timestamp"].to_numpy().astype(np.int64)
        close = np.column_stack([tape[s]["close"].to_numpy(float) for s in syms])
        opn = np.column_stack([tape[s]["open"].to_numpy(float) for s in syms])
        return cls(syms, ts, close, opn)

    @property
    def btc(self) -> int:
        return self.symbols.index("BTCUSD")


def signal(tape: Tape, kind: str, days: int) -> np.ndarray:
    """T x N booleans: may this coin be held at this bar?"""
    n = days * 24
    c = tape.close
    mom = np.full_like(c, np.nan)
    if len(c) > n:
        mom[n:] = c[n:] / c[:-n] - 1
    with np.errstate(invalid="ignore"):
        coin = mom > 0
        mkt = (mom[:, tape.btc] > 0)[:, None]
    if kind == "coin":
        return coin
    if kind == "market":
        return np.repeat(mkt, c.shape[1], axis=1) & ~np.isnan(c)
    if kind == "both":
        return coin & mkt
    if kind == "btc":
        out = np.zeros_like(coin)
        out[:, tape.btc] = coin[:, tape.btc]
        return out
    raise ValueError(f"unknown signal {kind!r}; choose from {', '.join(KINDS)}")


@dataclass
class Run:
    curve: np.ndarray         # equity from 1.0, one value per hour
    fees: float
    trades: int
    in_market: float          # share of hours holding anything

    @property
    def total(self) -> float:
        return float(self.curve[-1] - 1)

    @property
    def max_drawdown(self) -> float:
        return float((1 - self.curve / np.maximum.accumulate(self.curve)).max())


def simulate(tape: Tape, sig: np.ndarray, start: int, end: int, universe: list[int],
             fee: float = 0.0026) -> Run:
    idx = np.array(universe)
    decide = (tape.ts % 86400) == 82800           # the bar that opened 23:00 UTC closes the day
    cash, units = 1.0, np.zeros(tape.close.shape[1])
    fees, trades, invested = 0.0, 0, 0
    curve = np.empty(end - start + 1)
    for k, t in enumerate(range(start, end + 1)):
        px = tape.close[t]
        if t == start or decide[t]:
            slice_ = (cash + np.nansum(units[idx] * px[idx])) / len(idx)
            for i in idx:
                on = bool(sig[t, i])
                if not on and units[i] > 0:
                    proceeds = units[i] * px[i]
                    cash += proceeds * (1 - fee)
                    fees += proceeds * fee
                    units[i] = 0.0
                    trades += 1
                elif on and units[i] == 0 and cash > 1e-9 and not np.isnan(px[i]):
                    spend = min(slice_, cash)
                    units[i] = spend * (1 - fee) / px[i]
                    cash -= spend
                    fees += spend * fee
                    trades += 1
        curve[k] = cash + np.nansum(units[idx] * px[idx])
        invested += bool(units[idx].any())
    return Run(curve, fees, trades, invested / len(curve))


def windows(tape: Tape, frames: dict[str, pd.DataFrame], days: int = 30, stride_days: int = 10,
            warmup_bars: int = 720) -> list[tuple[int, int, list[int]]]:
    """The colony backtest's windows: (first bar, last bar, coins listed throughout)."""
    wbars = warmup_bars + days * 24
    out = []
    for s0 in range(0, len(tape.ts) - wbars + 1, stride_days * 24):
        present = window_symbols(frames, s0, wbars)
        if len(present) >= 2:
            out.append((s0 + warmup_bars, s0 + wbars - 1,
                        [tape.symbols.index(p) for p in present]))
    return out


def hold_return(tape: Tape, start: int, end: int, universe: list[int]) -> float:
    """Equal-weight buy and hold, no fees: the colony backtest's benchmark."""
    idx = np.array(universe)
    return float(np.mean(tape.close[end, idx] / tape.open[start, idx]) - 1)


def window_report(tape: Tape, frames, variants: list[tuple[str, int]], **kw) -> dict:
    """Per variant: mean, median, share positive, share beating hold, worst window, by year."""
    wins = windows(tape, frames, **kw)
    hold = [hold_return(tape, a, b, u) for a, b, u in wins]
    years = [pd.Timestamp(tape.ts[a], unit="s").year for a, _, _ in wins]

    def summary(rets):
        by: dict[int, list[float]] = {}
        for y, r in zip(years, rets):
            by.setdefault(y, []).append(r)
        return {"mean": statistics.fmean(rets), "median": statistics.median(rets),
                "positive": sum(r > 0 for r in rets) / len(rets),
                "beats_hold": sum(r > h for r, h in zip(rets, hold)) / len(rets),
                "worst": min(rets), "by_year": {y: statistics.fmean(v) for y, v in sorted(by.items())}}

    out = {"windows": len(wins), "hold": summary(hold)}
    for kind, days in variants:
        sig = signal(tape, kind, days)
        rets = [simulate(tape, sig, a, b, [tape.btc] if kind == "btc" else u).total
                for a, b, u in wins]
        out[f"{kind}-{days}d"] = summary(rets)
    return out
