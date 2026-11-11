"""The strategies' tear sheet: what each book held, against what came next."""
import pandas as pd
import pytest

from cryptoarena.arena.backtest import load_tape
from cryptoarena.arena.signals import (COLONY, forward_returns, format_tear_sheet, holdings,
                                       strategy_of, tear_sheet)
from cryptoarena.arena.survival import SurvivalConfig
from cryptoarena.cli import build_agents
from test_backtest import write_tape


def test_an_intern_counts_with_its_founders_strategy():
    assert strategy_of("momentum-3") == "momentum"
    assert strategy_of("bear-1") == "bear"
    assert strategy_of("index") == "index"


def test_holdings_are_read_at_every_close(tmp_path):
    write_tape(tmp_path, bars=720 + 24 * 6 + 1)
    frames = load_tape(tmp_path)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    h = holdings(frames, lambda: build_agents(5.0, False, ""), cfg, days=6, warmup_bars=720)
    assert h["window"].nunique() == 1
    assert h["ts"].nunique() == 6                                  # one read per day
    assert COLONY in set(h["strategy"]) and "momentum" in set(h["strategy"])
    assert set(h["symbol"]) == {"BTCUSD", "ETHUSD", "SOLUSD"}
    col = h[h["strategy"] == COLONY].groupby("ts")
    for _, day in col:                                             # weights add up to what is invested
        assert day["weight"].sum() == pytest.approx(day["invested"].iloc[0], abs=1e-9)


def frames_from(closes: dict[str, list[float]]):
    ts = [i * 86400 for i in range(len(next(iter(closes.values()))))]
    return {s: pd.DataFrame({"timestamp": ts, "open": c, "high": c, "low": c, "close": c,
                             "volume": 1.0}) for s, c in closes.items()}


def test_a_book_that_holds_what_rises_scores_high():
    frames = frames_from({"A": [1, 2, 4, 8, 16], "B": [1, 1, 1, 1, 1], "C": [4, 3, 2, 1, 0.5]})
    fwd = forward_returns(frames, 1)
    assert fwd.loc[0, "A"] == pytest.approx(1.0) and fwd.loc[3 * 86400, "C"] == pytest.approx(-0.5)
    rows = []
    for t in range(4):
        for s, good, bad in (("A", 0.5, 0.0), ("B", 0.3, 0.3), ("C", 0.0, 0.5)):
            rows.append((0, t * 86400, "good", s, good, 0.8))
            rows.append((0, t * 86400, "bad", s, bad, 0.8 if t % 2 else 0.6))
    hold = pd.DataFrame(rows, columns=["window", "ts", "strategy", "symbol", "weight", "invested"])
    sheet = {(f.strategy, f.horizon_days): f for f in tear_sheet(hold, frames, (1,), 1)}
    good, bad = sheet[("good", 1)], sheet[("bad", 1)]
    assert good.ic == pytest.approx(1.0) and bad.ic == pytest.approx(-1.0)
    assert good.spread > 0 > bad.spread
    assert good.turnover == 0.0 and good.days == 4
    text = format_tear_sheet(list(sheet.values()))
    assert "good" in text and "IC 1d" in text
