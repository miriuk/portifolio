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

    def predict(self, contexts: list, horizon: int) -> np.ndarray:
        """Per context (daily closes, oldest first, ending today), the
        predicted log return from today's close to `horizon` days later.
        A model with `wants_ohlcv = True` gets a DataFrame per context
        instead: timestamps, open, high, low, close, volume."""


@dataclass
class Daily:
    ts: np.ndarray            # unix seconds of the bar that closes each day
    bar: np.ndarray           # that bar's index on the tape
    close: np.ndarray
    ohlcv: np.ndarray | None = None   # n x 5: the day's open, high, low, close, volume


def daily_closes(tape: Tape, symbol: str | None = None) -> Daily:
    """One bar per day for `symbol` (the tape's lead by default): the
    stock bar itself, or the day of hourly candles that ends with the bar
    opening at 23:00 UTC."""
    i = tape.symbols.index(symbol or tape.lead_symbol)
    bars = tape.day_closes()
    c = tape.close[bars, i]
    ok = ~np.isnan(c)
    bars = bars[ok]
    ohlcv = None
    if tape.high is not None:
        k = tape.bars_per_day
        rows = []
        for b in bars:
            a = max(0, b - k + 1)
            rows.append([tape.open[a, i], np.nanmax(tape.high[a:b + 1, i]),
                         np.nanmin(tape.low[a:b + 1, i]), tape.close[b, i],
                         np.nansum(tape.volume[a:b + 1, i])])
        ohlcv = np.array(rows, float)
    return Daily(tape.ts[bars], bars, c[ok], ohlcv)


def walk_forward(daily: Daily, model: Forecaster, start: int, horizon: int = 7,
                 context_days: int | None = None, batch: int = 128) -> np.ndarray:
    """Predictions for every day from `start` on (NaN before), each made
    from the closes up to and including that day only."""
    n = len(daily.close)
    preds = np.full(n, np.nan)
    days = list(range(start, n))
    for k in range(0, len(days), batch):
        chunk = days[k:k + batch]
        spans = [((0 if context_days is None else max(0, d + 1 - context_days)), d + 1)
                 for d in chunk]
        if getattr(model, "wants_ohlcv", False) and daily.ohlcv is not None:
            ctx = [pd.DataFrame({"timestamps": pd.to_datetime(daily.ts[a:b], unit="s"),
                                 **{k: daily.ohlcv[a:b, j] for j, k in
                                    enumerate(("open", "high", "low", "close", "volume"))}})
                   for a, b in spans]
        else:
            ctx = [daily.close[a:b] for a, b in spans]
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
    ic = (float(pd.Series(p).corr(pd.Series(r), method="spearman"))
          if len(judged) > 2 and np.ptp(p) > 0 else float("nan"))   # a constant call ranks nothing
    sig = np.zeros_like(tape.close, dtype=bool)
    for d in range(start, n):
        sig[daily.bar[d], btc] = bool(preds[d] > 0)
    t0, t1 = int(daily.bar[start]), len(tape.ts) - 1
    run = simulate(tape, sig, t0, t1, [btc], fee=fee)
    years = (tape.ts[t1] - tape.ts[t0]) / (365.25 * 86400)
    return Verdict(name, len(judged), hit, float(np.mean(r > 0)) if judged else float("nan"), calls, ic,
                   _cagr(run.curve, years), run.max_drawdown, run.in_market, run.trades)


def benchmarks(tape: Tape, daily: Daily, start: int, fee: float = 0.0026,
               trend_days: int | None = None) -> list[Verdict]:
    """Hold the lead asset, and hold it with a trend exit (28 calendar days
    of crypto, 20 trading days of stocks) over the same span."""
    trend_days = trend_days or (28 if tape.bars_per_day == 24 else 20)
    t0, t1 = int(daily.bar[start]), len(tape.ts) - 1
    years = (tape.ts[t1] - tape.ts[t0]) / (365.25 * 86400)
    hold = tape.close[t0:t1 + 1, tape.btc] / tape.close[t0, tape.btc]
    trend = simulate(tape, signal(tape, "btc", trend_days), t0, t1, [tape.btc], fee=fee)
    nan = float("nan")
    name = tape.lead_symbol.replace("USD", "") if tape.lead_symbol.endswith("USD") else tape.lead_symbol
    return [Verdict(f"hold {name}", 0, nan, nan, nan, nan, _cagr(hold, years), _drawdown(hold), 1.0, 0),
            Verdict(f"{name}, {trend_days}-day trend exit", 0, nan, nan, nan, nan, _cagr(trend.curve, years),
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


def summarise(report: dict) -> str:
    """Across assets, per model: the mean edge over the base rate, the
    mean IC, and on how many assets it beat holding and the trend exit."""
    import statistics
    by_model: dict[str, list[dict]] = {}
    for sym, r in report.items():
        v = r["verdicts"]
        hold, trend = v[0], v[1]
        for m in v[2:]:
            by_model.setdefault(m["name"], []).append({
                "edge": m["hit_rate"] - m["base_rate"], "ic": m["ic"],
                "beats_hold": m["cagr"] > hold["cagr"], "beats_trend": m["cagr"] > trend["cagr"],
                "shallower": m["max_drawdown"] < hold["max_drawdown"]})
    n = len(report)
    lines = [f"across {n} assets:",
             f"{'model':<28} {'hit - base':>10} {'mean IC':>8} {'beats hold':>11} "
             f"{'beats trend':>12} {'smaller fall':>13}"]
    for name, rows in by_model.items():
        edge = statistics.fmean(r["edge"] for r in rows if r["edge"] == r["edge"])
        ic = statistics.fmean(r["ic"] for r in rows if r["ic"] == r["ic"])
        lines.append(f"{name:<28} {edge:>+10.1%} {ic:>+8.3f} "
                     f"{sum(r['beats_hold'] for r in rows):>6} of {len(rows):<3} "
                     f"{sum(r['beats_trend'] for r in rows):>6} of {len(rows):<4} "
                     f"{sum(r['shallower'] for r in rows):>6} of {len(rows):<4}")
    return "\n".join(lines)
