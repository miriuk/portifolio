"""The technical-analysis exam: what happened after each signal.

For every technique (agents/technical.py), every symbol and every bar a
signal fired, the trade it implies is entered at the *next* bar's open
and judged `h` bars later at the close. What counts is the return beyond
the symbol's own average `h`-bar return over the whole tape (so a bull
market does not make every buy signal look clever), signed by the
signal: a sell signal scores when the symbol then does worse than usual.
That catches both picking (which name) and timing (when); the moon, for
one, fires on every name the same day and can only be about timing.
`ex_cs`, the return beyond the universe's average over the same days, is
kept as a second reading: picking alone.

Signals bunch up in time (a market-wide drop fires the same buy on many
names at once), so the returns are averaged per block of `h` bars and
the t-statistic counts blocks, not trades. With twenty-one techniques,
two sides, two horizons and several universes, a few "significant"
results are expected by chance alone; the Benjamini–Hochberg q-value says
how many of them would survive that. A technique earns confidence only
when its edge holds after the correction and points the same way in most
universes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..agents.technical import TECHNIQUES, all_signals


@dataclass
class Result:
    universe: str
    technique: str
    side: int                 # +1 buy signals, -1 sell signals
    horizon: int
    events: int
    blocks: int
    edge: float               # mean signed excess return per trade (per block average)
    t: float
    hit: float                # share of trades whose signed excess was positive
    p: float = float("nan")
    q: float = float("nan")


def _p_two_sided(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2)) if t == t else float("nan")


def panel(frames: dict[str, pd.DataFrame], horizons=(5, 20)) -> pd.DataFrame:
    """One row per (symbol, bar): every technique's signal and the forward
    excess return over each horizon."""
    rows = []
    for sym, df in frames.items():
        df = df.dropna(subset=["close", "open"]).reset_index(drop=True)
        if len(df) < 150:
            continue
        sig = all_signals(df)
        out = sig.copy()
        out["ts"] = df["timestamp"].to_numpy()
        out["symbol"] = sym
        nxt_open = df["open"].shift(-1)
        for h in horizons:
            out[f"fwd{h}"] = df["close"].shift(-h) / nxt_open - 1
        rows.append(out)
    p = pd.concat(rows, ignore_index=True)
    for h in horizons:
        # beyond the symbol's usual h-bar return (timing and picking) ...
        p[f"ex{h}"] = p[f"fwd{h}"] - p.groupby("symbol")[f"fwd{h}"].transform("mean")
        # ... and beyond the universe's average that day (picking only)
        p[f"cs{h}"] = p[f"fwd{h}"] - p.groupby("ts")[f"fwd{h}"].transform("mean")
    return p


def examine(p: pd.DataFrame, universe: str, horizons=(5, 20), measure: str = "ex") -> list[Result]:
    days = np.sort(p["ts"].unique())
    rank = {d: i for i, d in enumerate(days)}
    out = []
    for name in TECHNIQUES:
        for side in (1, -1):
            hit_rows = p[p[name] == side]
            for h in horizons:
                ex = (hit_rows[f"{measure}{h}"] * side).dropna()
                if len(ex) < 20:
                    out.append(Result(universe, name, side, h, len(ex), 0, float("nan"),
                                      float("nan"), float("nan")))
                    continue
                block = hit_rows.loc[ex.index, "ts"].map(rank) // h
                per_block = ex.groupby(block).mean()
                n = len(per_block)
                sd = float(per_block.std()) if n > 1 else 0.0
                t = float(per_block.mean()) / (sd / math.sqrt(n)) if sd > 0 else float("nan")
                out.append(Result(universe, name, side, h, len(ex), n, float(per_block.mean()), t,
                                  float((ex > 0).mean())))
    return out


def correct(results: list[Result]) -> list[Result]:
    """Benjamini–Hochberg q-values over every test that ran."""
    tested = [r for r in results if r.t == r.t]
    for r in tested:
        r.p = _p_two_sided(r.t)
    order = sorted(tested, key=lambda r: r.p)
    m = len(order)
    q_prev = 1.0
    for i in range(m - 1, -1, -1):
        r = order[i]
        q_prev = min(q_prev, r.p * m / (i + 1))
        r.q = q_prev
    return results


GRADES = {"A": "a vantagem resiste à correção e aparece na maioria dos universos",
          "B": "positiva na maioria dos universos, mas não resiste à correção",
          "C": "sem direção: ora ajuda, ora atrapalha",
          "D": "aponta para o lado errado na maioria dos universos"}


def grades(results: list[Result], horizon: int = 20, alpha: float = 0.10) -> dict[str, dict]:
    """Per technique (both sides together): the grade and a confidence in
    [0, 1] the agents can weigh it by. Confidence is earned only by an A."""
    out = {}
    for name in TECHNIQUES:
        rs = [r for r in results if r.technique == name and r.horizon == horizon and r.t == r.t]
        if not rs:
            out[name] = {"grade": "C", "confidence": 0.0, "edge": float("nan"), "universes": 0}
            continue
        universes = sorted({r.universe for r in rs})
        by_u = {u: np.mean([r.edge for r in rs if r.universe == u]) for u in universes}
        positive = sum(v > 0 for v in by_u.values())
        survivors = [r for r in rs if r.q < alpha and r.edge > 0]
        mean_edge = float(np.mean(list(by_u.values())))
        if survivors and positive > len(universes) / 2:
            grade = "A"
        elif positive > len(universes) / 2:
            grade = "B"
        elif positive < len(universes) / 2:
            grade = "D"
        else:
            grade = "C"
        conf = 0.0
        if grade == "A":
            conf = round(min(1.0, max(positive / len(universes), 0.0)) * (1 - min(r.q for r in survivors)), 2)
        out[name] = {"grade": grade, "confidence": conf, "edge": mean_edge, "universes": len(universes),
                     "positive": positive, "survivors": len(survivors)}
    return out


def format_results(results: list[Result], horizon: int) -> str:
    unis = sorted({r.universe for r in results})
    lines = [f"{'técnica':<15}{'lado':>6}" + "".join(f"{u[:14]:>22}" for u in unis)]
    for name in TECHNIQUES:
        for side in (1, -1):
            cells = []
            for u in unis:
                r = next((r for r in results if (r.universe, r.technique, r.side, r.horizon) ==
                          (u, name, side, horizon)), None)
                if r is None or r.t != r.t:
                    cells.append(f"{'—':>22}")
                else:
                    star = "*" if r.q < 0.10 else " "
                    cells.append(f"{r.edge * 100:>+8.2f}% t{r.t:>+5.1f} n{r.events:>5}{star}")
            lines.append(f"{name:<15}{'compra' if side > 0 else 'venda':>6}" + "".join(cells))
    return "\n".join(lines)
