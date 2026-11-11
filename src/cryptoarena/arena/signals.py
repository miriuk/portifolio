"""Does a strategy's book predict anything? A factor tear sheet in the
spirit of alphalens (github.com/quantopian/alphalens, the idea, not its
code).

The colony's agents do not publish scores, they hold positions; what
they hold at each day's close *is* their signal. Over backtest windows
that do not overlap, every strategy's book (all its agents together: the
founder and the interns it hired) is read at each close as weights per
symbol, and set against what each symbol did next, over a day, a week and
a month:

- **IC**: the rank correlation, across the symbols, between the weights
  and the returns that followed. Positive means the strategy held more of
  what then rose. Its t-statistic counts overlapping horizons once.
- **pick spread**: what the symbols it held did next, minus the
  equal-weight universe: the return of the choice itself.
- **timing**: the correlation, over days, between how much it had
  invested and what the whole universe did next: did it step in before
  the rises and out before the falls?
- **turnover**: half the sum of the weight changes per day, the share of
  the book traded.

A strategy whose IC and spread hover around zero with a small t is not
choosing, it is only exposed; that is worth knowing before trusting it
with more of the colony.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..learning.memory import TradeJournal
from .backtest import TapeSlice, window_symbols
from .survival import SurvivalConfig, run_survival

COLONY = "colony"


def strategy_of(agent_id: str) -> str:
    """momentum-3 -> momentum: an intern counts with its founder's strategy."""
    head, _, tail = agent_id.rpartition("-")
    return head if tail.isdigit() and head else agent_id


def holdings(frames: dict[str, pd.DataFrame], make_founders, cfg: SurvivalConfig, days: int,
             stride_days: int | None = None, warmup_bars: int = 250,
             max_windows: int | None = None, sentiment: dict[int, int] | None = None) -> pd.DataFrame:
    """Each strategy's weights at every day's close over the backtest
    windows: rows (window, ts, strategy, symbol, weight, invested). The
    weight is the strategy's position value in the symbol over the
    strategy's equity (negative for a short); `COLONY` is everyone."""
    spd = cfg.steps_per_day
    stride_days = stride_days or days
    window_bars = warmup_bars + days * spd
    n = len(next(iter(frames.values())))
    starts = list(range(0, n - window_bars + 1, stride_days * spd))
    if max_windows:
        starts = starts[-max_windows:]
    wcfg = SurvivalConfig(**{**cfg.__dict__, "days": days, "warmup_bars": warmup_bars})
    rows: list[tuple] = []
    for w, start in enumerate(starts):
        present = window_symbols(frames, start, window_bars)
        if len(present) < 2:
            continue
        sub = {s: frames[s] for s in present}
        seen = {"bar": 0}

        def on_bar(agents, prices, ts, w=w, present=present, seen=seen):
            seen["bar"] += 1
            if seen["bar"] % spd:
                return                                      # only each day's last bar
            books: dict[str, list] = {}
            for a in agents:
                books.setdefault(strategy_of(a.agent_id), []).append(a)
            books[COLONY] = list(agents)
            for name, members in books.items():
                equity = sum(a.wallet.equity(prices) for a in members)
                if equity <= 0:
                    continue
                values = {s: sum(a.wallet.positions.get(s, 0.0) for a in members) * prices[s]
                          for s in present}
                invested = sum(values.values()) / equity
                for s in present:
                    rows.append((w, int(ts), name, s, values[s] / equity, invested))
        journal = TradeJournal(":memory:")
        try:
            run_survival(make_founders(), journal, wcfg, verbose=False,
                         market=TapeSlice(sub, start, window_bars, sentiment), on_bar=on_bar)
        finally:
            journal.close()
    return pd.DataFrame(rows, columns=["window", "ts", "strategy", "symbol", "weight", "invested"])


def forward_returns(frames: dict[str, pd.DataFrame], horizon_bars: int) -> pd.DataFrame:
    """ts x symbol: the close-to-close return over the next `horizon_bars`."""
    out = {}
    for sym, df in frames.items():
        c = df.set_index("timestamp")["close"].astype(float)
        out[sym] = c.shift(-horizon_bars) / c - 1
    return pd.DataFrame(out)


def _t(values: list[float], overlap: int = 1) -> float:
    """Mean over its standard error, with `overlap`-day horizons counted once."""
    if len(values) < 3:
        return float("nan")
    sd = statistics.pstdev(values)
    n_eff = max(1.0, len(values) / max(1, overlap))
    return statistics.fmean(values) / (sd / math.sqrt(n_eff)) if sd > 0 else float("nan")


@dataclass
class Factor:
    strategy: str
    horizon_days: int
    days: int
    ic: float
    ic_t: float
    spread: float              # held minus the universe, per horizon
    spread_t: float
    timing: float
    turnover: float
    extra: dict = field(default_factory=dict)


def tear_sheet(hold: pd.DataFrame, frames: dict[str, pd.DataFrame], horizons_days: tuple[int, ...],
               bars_per_day: int) -> list[Factor]:
    """One row per strategy and horizon (see the module doc)."""
    if hold.empty:
        return []
    out = []
    turnover = _turnover(hold)
    for h in horizons_days:
        fwd = forward_returns(frames, h * bars_per_day)
        f = hold.join(fwd.stack().rename("fwd"), on=["ts", "symbol"]).dropna(subset=["fwd"])
        for name, g in f.groupby("strategy", sort=True):
            ics, spreads, timing_x, timing_y = [], [], [], []
            for _, day in g.groupby(["window", "ts"]):
                w, r = day["weight"].to_numpy(), day["fwd"].to_numpy()
                timing_x.append(float(day["invested"].iloc[0]))
                timing_y.append(float(r.mean()))
                if len(w) >= 3 and np.ptp(w) > 0 and np.ptp(r) > 0:
                    ics.append(float(pd.Series(w).rank().corr(pd.Series(r).rank())))
                held = w > 1e-9
                if held.any():
                    spreads.append(float(r[held].mean() - r.mean()))
            tx, ty = np.array(timing_x), np.array(timing_y)
            timing = (float(pd.Series(tx).corr(pd.Series(ty), method="spearman"))
                      if len(tx) > 2 and np.ptp(tx) > 0 else float("nan"))
            out.append(Factor(
                name, h, len(timing_x),
                statistics.fmean(ics) if ics else float("nan"), _t(ics, h),
                statistics.fmean(spreads) if spreads else float("nan"), _t(spreads, h),
                timing, turnover.get(name, float("nan"))))
    return out


def _turnover(hold: pd.DataFrame) -> dict[str, float]:
    out = {}
    for name, g in hold.groupby("strategy"):
        per_day = []
        for _, win in g.groupby("window"):
            wide = win.pivot_table(index="ts", columns="symbol", values="weight").sort_index()
            if len(wide) > 1:
                per_day += list(wide.diff().abs().sum(axis=1).iloc[1:] / 2)
        out[name] = statistics.fmean(per_day) if per_day else float("nan")
    return out


def format_tear_sheet(rows: list[Factor]) -> str:
    if not rows:
        return "no holdings recorded"

    def num(x, fmt):
        return "—" if x != x else format(x, fmt)
    horizons = sorted({r.horizon_days for r in rows})
    head = f"{'strategy':<12}" + "".join(f" {'IC ' + str(h) + 'd':>8} {'t':>5}" for h in horizons) + \
        "".join(f" {'pick ' + str(h) + 'd':>9} {'t':>5}" for h in horizons) + \
        f" {'timing ' + str(horizons[-1]) + 'd':>10} {'turnover':>9}"
    lines = [head]
    by = {}
    for r in rows:
        by.setdefault(r.strategy, {})[r.horizon_days] = r
    names = sorted(by, key=lambda n: (n == COLONY, n))
    for name in names:
        d = by[name]
        line = f"{name:<12}"
        line += "".join(f" {num(d[h].ic, '+8.3f')} {num(d[h].ic_t, '+5.1f')}" for h in horizons)
        line += "".join(f" {num(d[h].spread * 100, '+8.2f')}% {num(d[h].spread_t, '+5.1f')}"
                        for h in horizons)
        last = d[horizons[-1]]
        line += f" {num(last.timing, '+10.3f')} {num(last.turnover, '9.1%')}"
        lines.append(line)
    return "\n".join(lines)
