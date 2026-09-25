"""Forecasters on trial: can a price-prediction model beat holding BTC?

Every model gets the same test. Once a day, at the close, it sees only
the daily closes up to that day and predicts the return over the next
`horizon` days. The strategy holds BTC while the prediction is positive
and sits in cash otherwise, traded by the same simulator and fees as
`arena/trend_hold.py`. It is judged on:

- hit rate: the predicted direction against the realised one, over the
  days the model took a side (a prediction of exactly zero, as a random
  walk gives, is no call), next to the base rate (how often BTC simply
  rose over `horizon` days), since a model that always says "up" already
  scores that;
- IC: the rank correlation between prediction and realised return;
- the strategy's growth, worst fall and time in the market, against
  holding BTC and against BTC with a 28-day trend exit over the same days.

The models come from open-source projects (see `models.py`); their
libraries are optional: `pip install -e ".[forecast]"` for the
statistical and gradient-boosting ones, `chronos-forecasting` (PyTorch
and the Hugging Face hub) for Chronos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ..arena.trend_hold import Tape, signal, simulate


class Forecaster(Protocol):
    name: str

    def predict(self, contexts: list[np.ndarray], horizon: int) -> np.ndarray:
        """Per context (daily closes, oldest first, ending today), the
        predicted log return from today's close to `horizon` days later."""


@dataclass
class Daily:
    ts: np.ndarray            # unix seconds of the bar that closes each day
    bar: np.ndarray           # that bar's index on the hourly tape
    close: np.ndarray


def daily_closes(tape: Tape, symbol: str = "BTCUSD") -> Daily:
    """The close of the bar that opens at 23:00 UTC: one price per day."""
    i = tape.symbols.index(symbol)
    bars = np.where((tape.ts % 86400) == 82800)[0]
    c = tape.close[bars, i]
    ok = ~np.isnan(c)
    return Daily(tape.ts[bars][ok], bars[ok], c[ok])


def walk_forward(daily: Daily, model: Forecaster, start: int, horizon: int = 7,
                 context_days: int | None = None, batch: int = 128) -> np.ndarray:
    """Predictions for every day from `start` on (NaN before), each made
    from the closes up to and including that day only."""
    n = len(daily.close)
    preds = np.full(n, np.nan)
    days = list(range(start, n))
    for k in range(0, len(days), batch):
        chunk = days[k:k + batch]
        ctx = [daily.close[(0 if context_days is None else max(0, d + 1 - context_days)):d + 1]
               for d in chunk]
        preds[chunk] = np.asarray(model.predict(ctx, horizon), float)
    return preds


def _cagr(curve: np.ndarray, years: float) -> float:
    return float(curve[-1] ** (1 / years) - 1) if years > 0 and curve[-1] > 0 else float("nan")


def _drawdown(curve: np.ndarray) -> float:
    return float((1 - curve / np.maximum.accumulate(curve)).max())


@dataclass
class Verdict:
    name: str
    days: int
    hit_rate: float
    base_rate: float
    calls: float              # share of days the model took a side
    ic: float
    cagr: float
    max_drawdown: float
    in_market: float
    trades: int
    extra: dict = field(default_factory=dict)


def evaluate(tape: Tape, daily: Daily, preds: np.ndarray, start: int, horizon: int = 7,
             name: str = "", fee: float = 0.0026) -> Verdict:
    btc = tape.btc
    n = len(daily.close)
    realised = np.full(n, np.nan)
    realised[:n - horizon] = np.log(daily.close[horizon:] / daily.close[:n - horizon])
    judged = [d for d in range(start, n - horizon) if not np.isnan(preds[d])]
    p, r = preds[judged], realised[judged]
    took = p != 0
    hit = float(np.mean(np.sign(p[took]) == np.sign(r[took]))) if took.any() else float("nan")
    calls = float(took.mean()) if judged else float("nan")
    ic = float(pd.Series(p).corr(pd.Series(r), method="spearman")) if len(judged) > 2 else float("nan")
    sig = np.zeros_like(tape.close, dtype=bool)
    for d in range(start, n):
        sig[daily.bar[d], btc] = bool(preds[d] > 0)
    t0, t1 = int(daily.bar[start]), len(tape.ts) - 1
    run = simulate(tape, sig, t0, t1, [btc], fee=fee)
    years = (tape.ts[t1] - tape.ts[t0]) / (365.25 * 86400)
    return Verdict(name, len(judged), hit, float(np.mean(r > 0)) if judged else float("nan"), calls, ic,
                   _cagr(run.curve, years), run.max_drawdown, run.in_market, run.trades)


def benchmarks(tape: Tape, daily: Daily, start: int, fee: float = 0.0026) -> list[Verdict]:
    """Hold BTC and BTC with a 28-day trend exit over the same span."""
    t0, t1 = int(daily.bar[start]), len(tape.ts) - 1
    years = (tape.ts[t1] - tape.ts[t0]) / (365.25 * 86400)
    hold = tape.close[t0:t1 + 1, tape.btc] / tape.close[t0, tape.btc]
    trend = simulate(tape, signal(tape, "btc", 28), t0, t1, [tape.btc], fee=fee)
    nan = float("nan")
    return [Verdict("hold BTC", 0, nan, nan, nan, nan, _cagr(hold, years), _drawdown(hold), 1.0, 0),
            Verdict("BTC, 28-day trend exit", 0, nan, nan, nan, nan, _cagr(trend.curve, years),
                    trend.max_drawdown, trend.in_market, trend.trades)]


def format_verdicts(rows: list[Verdict]) -> str:
    def pct(x, signed=True):
        return "—" if x != x else (f"{x:+.1%}" if signed else f"{x:.0%}")
    lines = [f"{'model':<26} {'calls':>5} {'hit':>5} {'base':>5} {'IC':>6} {'CAGR':>7} {'max fall':>8} "
             f"{'in mkt':>6} {'trades':>6}"]
    for v in rows:
        ic = "—" if v.ic != v.ic else f"{v.ic:+.3f}"
        lines.append(f"{v.name:<26} {pct(v.calls, False):>5} {pct(v.hit_rate, False):>5} "
                     f"{pct(v.base_rate, False):>5} "
                     f"{ic:>6} {pct(v.cagr):>7} {pct(v.max_drawdown, False):>8} "
                     f"{pct(v.in_market, False):>6} {v.trades:>6}")
    return "\n".join(lines)
