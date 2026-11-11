"""Did a backtest peek at the future? An audit in the spirit of freqtrade's
`lookahead-analysis` (github.com/freqtrade/freqtrade, the idea, not its
code): the most expensive mistake in a backtest is a decision that used
information it could not have had at the time, and it looks exactly like
skill.

Three checks:

1. **Scrambled future.** Run a window once; then run it again with every
   bar after a cut replaced by a different, made-up future (the same moves
   shuffled and sign-flipped, volumes shuffled, the Fear & Greed days after
   the cut shuffled too). Every trade and every hire, dismissal or award
   up to the cut must come out identical: a decision that changes when only
   the future changes was reading the future. The same test runs on any
   signal series (the trend exit, the forecasters).

2. **Delayed fill.** The simulator fills an order at the close of the bar
   the agent just saw. A real order reaches the market when it opens again:
   an hour later on a crypto tape, the next session on a daily stock tape,
   past the overnight gap. Running the same windows with fills at the next
   bar's open (`fill="next_open"`) measures how much of a result lived in
   that gap.

3. **Universe.** Which symbols a window trades: a symbol that disappears
   before the window ends is left out from its start, which is a peek; and
   a universe picked today (six mega caps, the coins still listed) carries
   hindsight no audit of the code can remove. `universe_check` counts the
   first; the second is reported in words.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..learning.memory import TradeJournal
from .backtest import TapeSlice, run_backtest, window_symbols
from .survival import SurvivalConfig, run_survival

PRICE_COLS = ("open", "high", "low", "close")


def scramble_after(frames: dict[str, pd.DataFrame], cut: int, seed: int = 0) -> dict[str, pd.DataFrame]:
    """A copy of row-aligned frames whose rows after `cut` are a made-up
    future: from the cut's close on, each symbol follows its own later
    log returns shuffled and randomly sign-flipped (open, high and low
    scaled with the close, so bars stay well-formed), volumes shuffled.
    Rows up to and including `cut` are untouched; missing bars stay missing."""
    rng = np.random.default_rng(seed)
    out = {}
    for sym, df in frames.items():
        df = df.copy()
        close = df["close"].to_numpy(float)
        n = len(close)
        if cut + 1 >= n or np.isnan(close[cut]):
            out[sym] = df
            continue
        later = np.arange(cut + 1, n)
        r = np.diff(np.log(close[cut:]))
        ok = ~np.isnan(r)
        shuffled = np.zeros_like(r)
        shuffled[ok] = rng.permutation(r[ok]) * rng.choice((-1.0, 1.0), ok.sum())
        path = close[cut] * np.exp(np.cumsum(shuffled))
        ratio = np.where(np.isnan(close[later]), np.nan, path / close[later])
        for col in PRICE_COLS:
            v = df[col].to_numpy(float).copy()
            v[later] = v[later] * ratio
            df[col] = v
        vol = df["volume"].to_numpy(float).copy()
        present = later[~np.isnan(vol[later])]
        vol[present] = rng.permutation(vol[present])
        df["volume"] = vol
        out[sym] = df
    return out


def scramble_sentiment(sentiment: dict[int, int] | None, cut_ts: int, seed: int = 0) -> dict[int, int]:
    """The Fear & Greed days after the cut's day shuffled among themselves."""
    if not sentiment:
        return {}
    day = cut_ts // 86400
    later = sorted(d for d in sentiment if d > day)
    vals = np.random.default_rng(seed).permutation([sentiment[d] for d in later])
    return {**{d: v for d, v in sentiment.items() if d <= day},
            **{d: int(v) for d, v in zip(later, vals)}}


def _r(x) -> float | str:
    return round(float(x), 9) if isinstance(x, (int, float, np.floating)) else x


def _run_window(frames, start: int, window_bars: int, cfg: SurvivalConfig, make_founders,
                sentiment) -> tuple[list[tuple], list[tuple]]:
    present = window_symbols(frames, start, window_bars)
    sub = {s: frames[s] for s in present}
    journal = TradeJournal(":memory:")
    try:
        run_survival(make_founders(), journal, cfg, verbose=False,
                     market=TapeSlice(sub, start, window_bars, sentiment))
        trades = [tuple(_r(v) for v in row) for row in journal._conn.execute(
            "SELECT timestamp, agent_id, symbol, side, quantity, price, fee, reason "
            "FROM trades ORDER BY rowid")]
        events = [tuple(_r(v) for v in row) for row in journal._conn.execute(
            "SELECT day, agent_id, event, equity, detail FROM survival_events ORDER BY rowid")]
    finally:
        journal.close()
    return trades, events


@dataclass
class Probe:
    cut_ts: int
    trades_checked: int
    events_checked: int
    mismatch: str | None = None      # the first decision that changed, if any


@dataclass
class ColonyAudit:
    start_ts: int
    probes: list[Probe] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return all(p.mismatch is None for p in self.probes)


def audit_colony(frames: dict[str, pd.DataFrame], make_founders, cfg: SurvivalConfig, start: int,
                 days: int, warmup_bars: int, cuts: list[int] | None = None, seed: int = 0,
                 sentiment: dict[int, int] | None = None) -> ColonyAudit:
    """Scrambled-future test of one backtest window (rows `start` ..
    `start + warmup_bars + days * steps_per_day`). `cuts` are bar offsets
    after the warm-up (default: a quarter, half and three quarters in)."""
    spd = cfg.steps_per_day
    window_bars = warmup_bars + days * spd
    wcfg = SurvivalConfig(**{**cfg.__dict__, "days": days, "warmup_bars": warmup_bars})
    cuts = cuts or [days * spd // 4, days * spd // 2, 3 * days * spd // 4]
    ts = frames[next(iter(frames))]["timestamp"].to_numpy()
    base_trades, base_events = _run_window(frames, start, window_bars, wcfg, make_founders, sentiment)
    audit = ColonyAudit(start_ts=int(ts[start + warmup_bars]))
    for k, off in enumerate(cuts):
        cut = start + warmup_bars + off
        cut_ts = int(ts[cut])
        # a day's events are filed at its last bar: whole days up to the cut
        last_day = (off + 1) // spd
        fr = scramble_after(frames, cut, seed + k)
        sent = scramble_sentiment(sentiment, cut_ts, seed + k)
        trades, events = _run_window(fr, start, window_bars, wcfg, make_founders, sent)
        want_t = [t for t in base_trades if t[0] <= cut_ts]
        got_t = [t for t in trades if t[0] <= cut_ts]
        want_e = [e for e in base_events if e[0] <= last_day]
        got_e = [e for e in events if e[0] <= last_day]
        probe = Probe(cut_ts, len(want_t), len(want_e))
        probe.mismatch = _first_difference("trade", want_t, got_t) or \
            _first_difference("event", want_e, got_e)
        audit.probes.append(probe)
    return audit


def _first_difference(kind: str, want: list[tuple], got: list[tuple]) -> str | None:
    for i, (a, b) in enumerate(zip(want, got)):
        if a != b:
            return f"{kind} #{i}: {a} became {b}"
    if len(want) != len(got):
        return f"{len(want)} {kind}s before the cut became {len(got)}"
    return None


def audit_series(compute, frames: dict[str, pd.DataFrame], cuts: list[int], seed: int = 0) -> list[str]:
    """Scrambled-future test of a signal: `compute(frames)` returns a
    Series indexed by timestamp (or a DataFrame); every value at or before
    a cut must be the same with the future scrambled. Returns the
    differences found (empty when clean)."""
    ts = frames[next(iter(frames))]["timestamp"].to_numpy()
    base = compute(frames)
    found = []
    for k, cut in enumerate(cuts):
        other = compute(scramble_after(frames, cut, seed + k))
        a = base[base.index <= ts[cut]]
        b = other[other.index <= ts[cut]]
        same = a.shape == b.shape and np.allclose(np.asarray(a, float), np.asarray(b, float),
                                                  rtol=1e-9, atol=1e-12, equal_nan=True)
        if not same:
            diff = (np.asarray(a, float) != np.asarray(b, float)) & \
                ~(np.isnan(np.asarray(a, float)) & np.isnan(np.asarray(b, float)))
            where = np.argwhere(diff.reshape(len(a), -1))
            at = pd.Timestamp(int(a.index[where[0][0]]), unit="s") if len(where) else "?"
            found.append(f"cut {pd.Timestamp(int(ts[cut]), unit='s')}: values before it changed "
                         f"(first at {at})")
    return found


def delay_report(frames, make_founders, cfg: SurvivalConfig, days: int, stride_days: int,
                 warmup_bars: int, max_windows: int | None = None,
                 sentiment: dict[int, int] | None = None) -> dict[str, dict]:
    """The same backtest windows filled at the close the agents saw and at
    the next bar's open: {"close": summary, "next_open": summary}."""
    out = {}
    for fill in ("close", "next_open"):
        c = SurvivalConfig(**{**cfg.__dict__, "fill": fill})
        rep = run_backtest(frames, make_founders, c, days=days, stride_days=stride_days,
                           warmup_bars=warmup_bars, max_windows=max_windows, sentiment=sentiment)
        out[fill] = rep.summary()
    return out


def universe_check(frames: dict[str, pd.DataFrame], days: int, stride_days: int, warmup_bars: int,
                   bars_per_day: int) -> dict:
    """How often a window leaves out a symbol that was trading when the
    window's first trading day began but has a hole before the window ends
    (delisted, halted, a long gap): knowing that at the start is a peek."""
    n = len(next(iter(frames.values())))
    window_bars = warmup_bars + days * bars_per_day
    windows = left_out = 0
    names: dict[str, int] = {}
    for start in range(0, n - window_bars + 1, stride_days * bars_per_day):
        present = set(window_symbols(frames, start, window_bars))
        if len(present) < 2:
            continue
        windows += 1
        first = start + warmup_bars
        for sym, df in frames.items():
            if sym in present:
                continue
            listed = not df["close"].iloc[start:first + 1].isna().any()
            if listed:
                left_out += 1
                names[sym] = names.get(sym, 0) + 1
    return {"windows": windows, "left_out": left_out, "symbols": names}


def format_delay(rep: dict[str, dict]) -> str:
    a, b = rep["close"], rep["next_open"]
    if not a or not b:
        return "no windows"
    lines = [f"{'':<16} {'at the close':>14} {'next open':>12} {'difference':>11}",
             f"{'colony mean':<16} {a['colony_mean']:>+14.2%} {b['colony_mean']:>+12.2%} "
             f"{(b['colony_mean'] - a['colony_mean']) * 100:>+10.2f}pt",
             f"{'beats hold':<16} {a['beats_hold']:>14.0%} {b['beats_hold']:>12.0%}"]
    if "pm_mean" in a and "pm_mean" in b:
        lines.append(f"{'PM book mean':<16} {a['pm_mean']:>+14.2%} {b['pm_mean']:>+12.2%} "
                     f"{(b['pm_mean'] - a['pm_mean']) * 100:>+10.2f}pt")
    for s in a["strategies"]:
        if s in b["strategies"]:
            x, y = a["strategies"][s]["mean"], b["strategies"][s]["mean"]
            lines.append(f"  {s:<14} {x:>+14.2%} {y:>+12.2%} {(y - x) * 100:>+10.2f}pt")
    lines.append(f"{'hold (same)':<16} {a['hold_mean']:>+14.2%} {b['hold_mean']:>+12.2%}")
    return "\n".join(lines)
