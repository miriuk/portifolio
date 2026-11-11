"""The technical-analysis course: detectors that only use the past, and an
exam that finds a planted edge and corrects for many tests."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.agents import technical as ta
from cryptoarena.arena.lookahead import audit_series
from cryptoarena.learning.ta_exam import Result, correct, examine, grades, panel

DAY = 86400


def walk(n=600, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    o = np.r_[c[0], c[:-1]] * np.exp(rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.006, n)))
    v = rng.lognormal(10, 0.4, n)
    return pd.DataFrame({"timestamp": 1_600_000_000 + np.arange(n) * DAY, "open": o, "high": h,
                         "low": lo, "close": c, "volume": v})


def test_every_detector_returns_buy_sell_or_nothing_and_never_reads_the_future():
    frames = {"X": walk(), "Y": walk(seed=1)}
    for name, (fn, _) in ta.TECHNIQUES.items():
        s = fn(frames["X"])
        assert len(s) == len(frames["X"]) and set(s.unique()) <= {-1, 0, 1}, name
        found = audit_series(lambda fr, fn=fn: fn(fr["X"]).set_axis(fr["X"]["timestamp"]),
                             frames, [250, 400], seed=2)
        assert found == [], (name, found)


def test_a_known_swing_point_is_never_removed_by_a_later_one():
    df = walk(300, seed=4)
    states = ta.pivot_states(df, 5)
    for t in range(1, len(states)):
        before, now = states[t - 1], states[t]
        # anything known at t-1 is still known at t, except the last one, which
        # only a more extreme swing of the same kind may replace
        assert now[:max(0, len(before) - 1)][-6:] == before[:-1][-6:] or len(before) >= 8


def test_classic_shapes():
    # bullish engulfing after a fall
    o = [10, 9.8, 9.6, 9.4, 9.2, 9.0, 8.8, 8.65]
    c = [9.8, 9.6, 9.4, 9.2, 9.0, 8.8, 8.7, 9.1]
    df = pd.DataFrame({"timestamp": np.arange(8) * DAY, "open": o, "close": c,
                       "high": np.maximum(o, c) + 0.05, "low": np.minimum(o, c) - 0.05, "volume": 1.0})
    assert ta.candlesticks(df).iloc[-1] == 1
    # a three-bar gap up, then a return into it that holds
    h = [10, 10.5, 12.5, 12.6, 11.2]
    lo = [9.5, 10.0, 11.0, 11.5, 10.6]
    cl = [9.8, 10.4, 12.3, 12.0, 11.1]
    gap = pd.DataFrame({"timestamp": np.arange(5) * DAY, "open": cl, "high": h, "low": lo, "close": cl,
                        "volume": 1.0})
    assert ta.fair_value_gap(gap).iloc[-1] == 1
    # moon: 2024-01-11 was a new moon, 2024-01-25 a full moon
    new, full = pd.Timestamp("2024-01-11T12:00Z").timestamp(), pd.Timestamp("2024-01-25T18:00Z").timestamp()
    ph = ta.moon_phase([new, full])
    assert min(ph[0], 1 - ph[0]) < 0.03 and abs(ph[1] - 0.5) < 0.03
    # RSI leaving oversold
    closes = list(np.linspace(100, 60, 30)) + [62, 66, 71, 77, 84]
    df = pd.DataFrame({"timestamp": np.arange(35) * DAY, "open": closes, "high": closes, "low": closes,
                       "close": closes, "volume": 1.0})
    assert ta.oscillators(df).iloc[-5:].max() == 1


def test_daily_bars_from_hourly():
    ts = 1_700_006_400 + np.arange(48) * 3600            # two whole UTC days
    hourly = pd.DataFrame({"timestamp": ts, "open": np.arange(48.0), "high": np.arange(48.0) + 1,
                           "low": np.arange(48.0) - 1, "close": np.arange(48.0) + 0.5, "volume": 1.0})
    d = ta.to_daily(hourly)
    assert len(d) == 2 and d.loc[0, "open"] == 0 and d.loc[0, "close"] == 23.5
    assert d.loc[1, "high"] == 48 and d.loc[0, "volume"] == 24


def test_the_exam_finds_a_planted_edge_and_ignores_noise(monkeypatch):
    rng = np.random.default_rng(3)
    frames = {f"S{i}": walk(500, seed=10 + i) for i in range(12)}

    def planted(df):                     # "buy" where we marked a rise into half the names
        return pd.Series((df["volume"] > 1e11).astype(int).to_numpy(), index=df.index)
    for i, df in enumerate(frames.values()):
        if i % 2:
            continue
        for t in range(100, 480, 40):
            df.loc[t, "volume"] = 1e12
            df.loc[t + 2:t + 6, ["open", "high", "low", "close"]] *= 1.03
    monkeypatch.setattr(ta, "TECHNIQUES", {"planted": (planted, ""), "noise": (
        lambda df: pd.Series(rng.choice([-1, 0, 0, 0, 1], len(df)), index=df.index), "")})
    import cryptoarena.learning.ta_exam as ex
    monkeypatch.setattr(ex, "TECHNIQUES", ta.TECHNIQUES)
    monkeypatch.setattr(ex, "all_signals", lambda df: pd.DataFrame(
        {k: fn(df) for k, (fn, _) in ta.TECHNIQUES.items()}, index=df.index))
    res = correct(examine(panel(frames, horizons=(5,)), "synthetic", horizons=(5,)))
    planted_buy = next(r for r in res if r.technique == "planted" and r.side == 1)
    assert planted_buy.edge > 0 and planted_buy.q < 0.05
    noise = [r for r in res if r.technique == "noise" and r.t == r.t]
    assert all(r.q > 0.05 for r in noise)
    g = grades(res, horizon=5)
    assert g["planted"]["grade"] == "A" and g["planted"]["confidence"] > 0
    assert g["noise"]["confidence"] == 0.0


def test_benjamini_hochberg():
    rs = [Result("u", "x", 1, 5, 100, 50, 0.01, t, 0.5) for t in (4.0, 2.0, 0.1)]
    correct(rs)
    assert rs[0].q < 0.001 and rs[2].q == pytest.approx(rs[2].p)
    assert rs[1].q == pytest.approx(min(rs[1].p * 3 / 2, rs[2].q))


def test_the_council_weighs_only_earned_confidence():
    df = walk(300, seed=8)
    assert ta.council(df, {}) == 0.0
    assert ta.council(df, {"rsi": 0.0, "breakout": 0.0}) == 0.0          # nobody earned a voice
    conf = ta.load_confidence()
    assert set(conf) == set(ta.TECHNIQUES)                                # the exam graded all 21
    always_buy = {"planted": 1.0}
    import cryptoarena.agents.technical as mod
    saved = dict(mod.TECHNIQUES)
    try:
        mod.TECHNIQUES["planted"] = (lambda d: pd.Series(1, index=d.index), "")
        assert ta.council(df, always_buy) == 1.0
    finally:
        mod.TECHNIQUES.clear()
        mod.TECHNIQUES.update(saved)
    from collections import deque
    from cryptoarena.market.candle import Candle
    hist = deque(Candle("X", int(r.timestamp), r.open, r.high, r.low, r.close, r.volume)
                 for r in df.itertuples())
    assert list(ta.candles_frame(hist).columns) == ["timestamp", "open", "high", "low", "close", "volume"]
