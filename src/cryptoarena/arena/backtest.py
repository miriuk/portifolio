"""Walk-forward backtests of the survival colony on real candles.

A window is a fresh colony (fresh founders, fresh journal in memory) that
lives `days` real days on a slice of the tape, after `warmup_bars` of
history for its indicators. Windows start every `stride_days`, so a year
of data gives a few dozen colonies whose returns can be compared with
buy-and-hold over the same hours — the honest question is not "did it
make money" but "did it beat holding the coins, net of fees".

    python -m cryptoarena.cli backtest --data data/ --days 30 --stride 10
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..learning.memory import TradeJournal
from ..market.candle import Candle
from .survival import SurvivalConfig, run_survival


def load_tape(data_dir: str | Path, symbols: list[str] | None = None,
              align: bool = True, fill_gaps: int = 6) -> dict[str, pd.DataFrame]:
    """CSVs (timestamp, open, high, low, close, volume), oldest first.

    `align=True`: only the timestamps every symbol has (a fixed universe).
    `align=False`: every symbol on the union timeline, missing bars as NaN
    (a gap of up to `fill_gaps` bars is carried forward): a coin listed in
    2023 is simply absent before that, and each backtest window trades the
    coins that exist for the whole of it — a universe that grows with the
    years instead of a list of today's survivors."""
    data_dir = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(data_dir.glob("*.csv")):
        if symbols and path.stem not in symbols:
            continue
        df = pd.read_csv(path).sort_values("timestamp").drop_duplicates("timestamp")
        frames[path.stem] = df.set_index("timestamp")
    if not frames:
        raise FileNotFoundError(f"no CSVs in {data_dir}")
    if align:
        common = None
        for df in frames.values():
            common = df.index if common is None else common.intersection(df.index)
        return {sym: df.loc[common].reset_index() for sym, df in frames.items()}
    union = None
    for df in frames.values():
        union = df.index if union is None else union.union(df.index)
    out = {}
    for sym, df in frames.items():
        full = df.reindex(union)
        if fill_gaps:
            present = full["close"].notna()
            filled = full.ffill(limit=fill_gaps)
            filled.loc[~present, "volume"] = 0.0            # a carried bar traded nothing
            first = present.idxmax() if present.any() else None
            if first is not None:
                filled.loc[filled.index < first] = float("nan")   # never fill before the listing
            full = filled
        out[sym] = full.reset_index()
    return out


def window_symbols(tape: dict[str, pd.DataFrame], start: int, length: int) -> list[str]:
    """The symbols with a complete tape over rows [start, start + length)."""
    return [sym for sym, df in tape.items()
            if not df["close"].iloc[start:start + length].isna().any()]


def load_sentiment(data_dir: str | Path) -> dict[int, int]:
    """The Crypto Fear & Greed index by UTC day (`sentiment/fng.csv` as the
    market-data workflow publishes it); empty when the file is absent."""
    path = Path(data_dir) / "sentiment" / "fng.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return {int(ts) // 86400: int(v) for ts, v in zip(df["timestamp"], df["value"])}


class TapeSlice:
    """A market that replays rows [start, start + length) of aligned frames,
    and knows the day's sentiment when a Fear & Greed history is given."""

    def __init__(self, tape: dict[str, pd.DataFrame], start: int, length: int,
                 sentiment: dict[int, int] | None = None):
        self._rows = {sym: df.iloc[start:start + length].to_numpy() for sym, df in tape.items()}
        self._cols = {sym: list(df.columns) for sym, df in tape.items()}
        self._i = 0
        self._length = length
        self._regime: dict[str, str] = {}
        self._sentiment = sentiment or {}

    def sentiment_at(self, ts: int) -> int | None:
        day = ts // 86400
        for back in range(0, 4):                    # the index is daily; tolerate a gap
            if day - back in self._sentiment:
                return self._sentiment[day - back]
        return None

    def next_candles(self) -> list[Candle]:
        if self._i >= self._length:
            raise StopIteration("tape exhausted")
        out = []
        for sym, rows in self._rows.items():
            c = self._cols[sym]
            r = rows[self._i]
            out.append(Candle(sym, int(r[c.index("timestamp")]), float(r[c.index("open")]),
                              float(r[c.index("high")]), float(r[c.index("low")]),
                              float(r[c.index("close")]), float(r[c.index("volume")])))
        self._i += 1
        return out


@dataclass
class WindowResult:
    start_ts: int
    end_ts: int
    colony_return: float                    # final colony equity / total founding budget - 1
    hold_return: float                      # equal-weight buy-and-hold over the same bars
    by_strategy: dict[str, float]           # founder lineage value (self + hires) / budget - 1
    hires: int
    dismissed: int
    fees: float
    target_hits: int
    target_days: int
    symbols: int = 0                        # coins that existed for the whole window


@dataclass
class BacktestReport:
    windows: list[WindowResult] = field(default_factory=list)

    def by_year(self) -> dict[int, dict]:
        """The same summary per calendar year of the window's start: the
        regimes a multi-year tape contains, one row each."""
        years: dict[int, list[WindowResult]] = {}
        for w in self.windows:
            years.setdefault(pd.Timestamp(w.start_ts, unit="s").year, []).append(w)
        out = {}
        for year, ws in sorted(years.items()):
            colony = [w.colony_return for w in ws]
            hold = [w.hold_return for w in ws]
            strategies = sorted({s for w in ws for s in w.by_strategy})
            out[year] = {
                "windows": len(ws),
                "symbols": round(statistics.fmean(w.symbols for w in ws), 1),
                "colony_mean": statistics.fmean(colony), "hold_mean": statistics.fmean(hold),
                "colony_positive": sum(c > 0 for c in colony) / len(ws),
                "beats_hold": sum(c > h for c, h in zip(colony, hold)) / len(ws),
                "strategies": {s: statistics.fmean(w.by_strategy[s] for w in ws if s in w.by_strategy)
                               for s in strategies},
            }
        return out

    def summary(self) -> dict:
        if not self.windows:
            return {}
        colony = [w.colony_return for w in self.windows]
        hold = [w.hold_return for w in self.windows]
        strategies = sorted({s for w in self.windows for s in w.by_strategy})
        per = {}
        for s in strategies:
            rs = [w.by_strategy[s] for w in self.windows if s in w.by_strategy]
            per[s] = {"mean": statistics.fmean(rs), "median": statistics.median(rs),
                      "positive": sum(r > 0 for r in rs) / len(rs),
                      "beats_hold": sum(r > w.hold_return for r, w in zip(rs, self.windows)) / len(rs)}
        return {
            "windows": len(self.windows),
            "colony_mean": statistics.fmean(colony), "colony_median": statistics.median(colony),
            "colony_positive": sum(r > 0 for r in colony) / len(colony),
            "hold_mean": statistics.fmean(hold),
            "beats_hold": sum(c > h for c, h in zip(colony, hold)) / len(colony),
            "hires": sum(w.hires for w in self.windows),
            "dismissed": sum(w.dismissed for w in self.windows),
            "fees": sum(w.fees for w in self.windows),
            "target_hit_rate": sum(w.target_hits for w in self.windows)
            / max(1, sum(w.target_days for w in self.windows)),
            "strategies": per,
        }


def run_backtest(tape: dict[str, pd.DataFrame], make_founders, cfg: SurvivalConfig,
                 days: int = 30, stride_days: int = 10, warmup_bars: int = 150,
                 max_windows: int | None = None, verbose: bool = False,
                 sentiment: dict[int, int] | None = None) -> BacktestReport:
    """`make_founders()` returns a fresh list of founder agents each call.
    `sentiment` (UTC day -> Fear & Greed) lets the agents' greed gate act."""
    bars_per_day = cfg.steps_per_day
    n = len(next(iter(tape.values())))
    window_bars = warmup_bars + days * bars_per_day
    starts = list(range(0, n - window_bars + 1, stride_days * bars_per_day))
    if max_windows:
        starts = starts[-max_windows:]
    report = BacktestReport()
    for start in starts:
        present = window_symbols(tape, start, window_bars)
        if len(present) < min(2, len(tape)):
            continue                                    # nothing listed yet: no market to trade
        sub = {sym: tape[sym] for sym in present}
        market = TapeSlice(sub, start, window_bars, sentiment)
        journal = TradeJournal(":memory:")
        founders = make_founders()
        wcfg = SurvivalConfig(**{**cfg.__dict__, "days": days, "warmup_bars": warmup_bars})
        try:
            res = run_survival(founders, journal, wcfg, verbose=False, market=market)
            w = _summarise(sub, start, warmup_bars, window_bars, res, journal)
            w.symbols = len(present)
            report.windows.append(w)
        finally:
            journal.close()
        if verbose:
            w = report.windows[-1]
            print(f"{pd.Timestamp(w.start_ts, unit='s'):%Y-%m-%d}  {w.symbols:2d} coins  "
                  f"colony {w.colony_return:+.1%}  hold {w.hold_return:+.1%}  hires {w.hires}  "
                  f"let go {w.dismissed}  "
                  + "  ".join(f"{s} {r:+.1%}" for s, r in w.by_strategy.items()), flush=True)
    return report


def _summarise(tape, start, warmup, window_bars, res, journal) -> WindowResult:
    first, last = start + warmup, start + window_bars - 1
    hold = statistics.fmean(
        float(df.iloc[last]["close"]) / float(df.iloc[first]["open"]) - 1 for df in tape.values())
    prices = {sym: float(df.iloc[last]["close"]) for sym, df in tape.items()}
    founding = sum(i.budget for i in res.population if i.generation == 0)
    total = sum(i.agent.wallet.equity(prices) for i in res.alive)
    # a founder's result includes the children it paid for: the lineage's worth
    parent_of = {i.agent_id: i.parent_id for i in res.population}
    lineage: dict[str, float] = {}
    for ind in res.population:
        root = ind.agent_id
        while parent_of.get(root):
            root = parent_of[root]
        lineage[root] = lineage.get(root, 0.0) + (ind.agent.wallet.equity(prices) if ind.alive else 0.0)
    by_strategy = {i.agent_id: lineage.get(i.agent_id, 0.0) / i.budget - 1
                   for i in res.population if i.generation == 0}
    fees = journal._conn.execute("SELECT COALESCE(SUM(fee), 0) FROM trades").fetchone()[0]
    hits = journal._conn.execute(
        "SELECT COUNT(*) FROM survival_events WHERE event = 'target_hit'").fetchone()[0]
    survived = journal._conn.execute(
        "SELECT COUNT(*) FROM survival_events WHERE event = 'survived'").fetchone()[0]
    return WindowResult(
        start_ts=int(tape[next(iter(tape))].iloc[first]["timestamp"]),
        end_ts=int(tape[next(iter(tape))].iloc[last]["timestamp"]),
        colony_return=total / founding - 1, hold_return=hold, by_strategy=by_strategy,
        hires=sum(1 for i in res.population if i.generation > 0),
        dismissed=sum(1 for i in res.population if not i.alive),
        fees=fees, target_hits=hits, target_days=survived)


def format_by_year(by_year: dict[int, dict], strategies: tuple[str, ...] = ()) -> str:
    """One line per year: windows, coins, colony, hold, beats hold, and the
    founders asked for."""
    if not by_year:
        return "no windows"
    lines = []
    for year, d in by_year.items():
        extra = "".join(f"  {s} {d['strategies'][s]:+.1%}" for s in strategies if s in d["strategies"])
        lines.append(f"{year}: {d['windows']:3d} windows · {d['symbols']:4.1f} coins · "
                     f"colony {d['colony_mean']:+.2%} (positive {d['colony_positive']:.0%}) · "
                     f"hold {d['hold_mean']:+.2%} · beats hold {d['beats_hold']:.0%}{extra}")
    return "\n".join(lines)


def format_summary(summary: dict) -> str:
    if not summary:
        return "no windows"
    lines = [
        f"{summary['windows']} windows · colony mean {summary['colony_mean']:+.2%} "
        f"(median {summary['colony_median']:+.2%}, positive {summary['colony_positive']:.0%}) · "
        f"buy&hold mean {summary['hold_mean']:+.2%} · beats hold {summary['beats_hold']:.0%}",
        f"hires {summary['hires']} · let go {summary['dismissed']} · fees {summary['fees']:.2f} · "
        f"daily target hit {summary['target_hit_rate']:.0%} of agent-days",
    ]
    for s, d in summary["strategies"].items():
        lines.append(f"  {s:<14} mean {d['mean']:+.2%}  median {d['median']:+.2%}  "
                     f"positive {d['positive']:.0%}  beats hold {d['beats_hold']:.0%}")
    return "\n".join(lines)
