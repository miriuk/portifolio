"""Courses 3 and 4 of the academy: a portfolio simulator, and how not to
fool yourself with it.

Course 3 (chapter 4 of *Algorithmic Trading with Python*, Chris Conlan,
2020) is the simplest honest simulator of a stock picker: each day, at the
close, sell every position whose signal says -1, then fill the free slots
(at most `max_positions` names) with the names whose signal says +1,
ranked by a *preference* (which of the candidates to take first), each
slot getting an equal share of the cash; percentage slippage and a fixed
fee per trade. The colony's own engine (arena/episode.py) does more; this
one is vectorised and fast enough to run a thousand times.

Course 4 (chapter 5) is why one would: a backtest that looks good may
just be lucky. Two tests from the book:

- **white noise**: run the same signal with a *random* preference, many
  times. If the real preference is not clearly better than the noise
  runs, the ranking adds nothing;
- **bootstrap**: the preference is a rolling Sharpe ratio computed on
  resampled returns, so it has the right statistical shape but no
  information. Same question.

The answer is a percentile: where the real result falls among the runs
that cannot know anything. Written from the book's description; its code
is freeware for personal use only and is not copied here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def simulate(prices: pd.DataFrame, signal: pd.DataFrame, preference: pd.DataFrame,
             max_positions: int = 5, cash: float = 10_000.0, slippage: float = 0.0005,
             fee: float = 0.0) -> pd.Series:
    """The equity curve, one value per row of `prices` (dates × symbols)."""
    px = prices.to_numpy(float)
    sig = signal.reindex_like(prices).to_numpy(float)
    pref = preference.reindex_like(prices).to_numpy(float)
    n_days, n_sym = px.shape
    units = np.zeros(n_sym)
    last = np.zeros(n_sym)                     # a name with no price today keeps its last one
    equity = np.empty(n_days)
    for t in range(n_days):
        p = px[t]
        ok = ~np.isnan(p)
        last = np.where(ok, p, last)
        held = units > 0
        for i in np.where(held & ok & (sig[t] < 0))[0]:      # sell to close
            cash += units[i] * p[i] * (1 - slippage) - fee
            units[i] = 0.0
        held = units > 0
        free = max_positions - int(held.sum())
        if free > 0:
            cands = np.where(ok & ~held & (sig[t] > 0) & ~np.isnan(pref[t]))[0]
            if len(cands):
                pick = cands[np.argsort(-pref[t][cands], kind="stable")][:free]
                budget = cash / free
                for i in pick:
                    if budget <= fee:
                        continue
                    units[i] = (budget - fee) / (p[i] * (1 + slippage))
                    cash -= budget
        equity[t] = cash + float((units * last).sum())
    return pd.Series(equity, index=prices.index)


def bollinger_signal(prices: pd.DataFrame, n: int = 20, width: float = 2.0) -> pd.DataFrame:
    mean = prices.rolling(n).mean()
    sd = prices.rolling(n).std()
    return (prices < mean - width * sd).astype(int) - (prices > mean + width * sd).astype(int)


def macd_signal(prices: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.DataFrame:
    sign = np.sign(prices.rolling(fast).mean() - prices.rolling(slow).mean())
    return sign * (sign != sign.shift(1))


def rolling_sharpe(prices: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    r = prices.pct_change()
    return r.rolling(n).mean() / r.rolling(n).std()


def excess_cagr(equity: pd.Series, benchmark: pd.Series) -> float:
    years = (equity.index[-1] - equity.index[0]) / (365.25 * 86400)
    if years <= 0:
        return float("nan")
    a = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    b = (benchmark.iloc[-1] / benchmark.iloc[0]) ** (1 / years) - 1
    return float(a - b)


@dataclass
class NullTest:
    name: str
    real: float                  # the real preference's excess CAGR over the benchmark
    runs: np.ndarray             # the same under preferences that know nothing

    @property
    def percentile(self) -> float:
        return float((self.runs < self.real).mean())

    def summary(self) -> str:
        q = np.percentile(self.runs, [5, 50, 95])
        return (f"{self.name}: real {self.real:+.2%} a year vs the benchmark; {len(self.runs)} "
                f"runs that know nothing: median {q[1]:+.2%}, 90% between {q[0]:+.2%} and "
                f"{q[2]:+.2%}; the real one beats {self.percentile:.0%} of them")


def white_noise_test(prices, signal, preference, benchmark, runs: int = 200, seed: int = 0,
                     **sim) -> NullTest:
    rng = np.random.default_rng(seed)
    real = excess_cagr(simulate(prices, signal, preference, **sim), benchmark)
    out = []
    for _ in range(runs):
        noise = pd.DataFrame(rng.standard_normal(prices.shape), index=prices.index,
                             columns=prices.columns)
        out.append(excess_cagr(simulate(prices, signal, noise, **sim), benchmark))
    return NullTest("white noise", real, np.array(out))


def bootstrap_test(prices, signal, preference, benchmark, runs: int = 200, n: int = 20,
                   seed: int = 0, **sim) -> NullTest:
    rng = np.random.default_rng(seed)
    real = excess_cagr(simulate(prices, signal, preference, **sim), benchmark)
    r = prices.pct_change()
    out = []
    for _ in range(runs):
        boot = r.apply(lambda col: pd.Series(
            rng.choice(col.dropna().to_numpy(), size=len(col)) if col.notna().sum() else col.to_numpy(),
            index=col.index))
        pref = boot.rolling(n).mean() / boot.rolling(n).std()
        out.append(excess_cagr(simulate(prices, signal, pref, **sim), benchmark))
    return NullTest("bootstrap", real, np.array(out))
