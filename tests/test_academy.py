"""The academy's courses (Algorithmic Trading with Python, rewritten)."""
from collections import deque

import numpy as np
import pandas as pd
import pytest

from cryptoarena.agents.base import MarketView
from cryptoarena.agents.rules import BollingerAgent, ChaikinAgent, MacdAgent
from cryptoarena.arena import booksim as bs
from cryptoarena.forecast.events import average_uniqueness, cusum_events, triple_barrier
from cryptoarena.learning.academy import COURSES, colony_report_cards, format_cards
from cryptoarena.market.candle import Candle
from cryptoarena.portfolio import metrics as m

DAY = 86400


def curve(values, step=DAY):
    return pd.Series(values, index=[i * step for i in range(len(values))], dtype=float)


def test_course_1_measures():
    up = curve([100 * 1.001 ** i for i in range(366)])            # steady growth, a year
    assert m.cagr(up) == pytest.approx(1.001 ** 365 - 1, rel=1e-3)
    assert m.max_drawdown(up) == 0 and m.pure_profit_score(up) == pytest.approx(m.cagr(up), rel=1e-6)
    bumpy = curve([100, 110, 90, 120, 60, 130])
    info = m.max_drawdown_info(bumpy)
    assert info["drawdown"] == pytest.approx(0.5) and info["peak"] == 3 * DAY and info["bottom"] == 4 * DAY
    assert info["recovered"] == 5 * DAY
    assert m.sortino(bumpy) != m.sharpe(bumpy)
    bench = curve([100, 101, 99, 102, 98, 103])
    twice = curve(100 * np.cumprod([1] + [1 + 2 * r for r in m.returns(bench)]))
    assert m.beta(twice, bench) == pytest.approx(2.0) and abs(m.jensens_alpha(twice, bench)) < 1e-9
    card = m.report_card(up, up)
    assert set(card) >= {"cagr", "sharpe", "sortino", "max_drawdown", "calmar", "alpha", "beta"}


def candles(closes, highs=None, lows=None, vols=None):
    return [Candle("X", i * DAY, c, highs[i] if highs else c * 1.01, lows[i] if lows else c * 0.99, c,
                   vols[i] if vols else 100.0) for i, c in enumerate(closes)]


def decide(agent, cs, held=0.0):
    agent.history = {"X": deque(cs, maxlen=720)}
    agent.wallet.positions["X"] = held
    last = cs[-1]
    return agent.decide(MarketView({"X": last}, agent.history, {"X": last.close}, step=1000))


def test_course_2_graduates():
    falling_then_up = [100 - i for i in range(40)] + [61 + 3 * i for i in range(8)]
    macd = MacdAgent("macd-1", 1000.0, params={"fast": 5, "slow": 34, "cooldown": 0})
    sides = []
    for k in range(40, len(falling_then_up) + 1):
        sides += [o.side for o in decide(macd, candles(falling_then_up[:k]))]
    assert sides.count("buy") == 1                                 # one cross up, one buy
    calm = [100 + (i % 2) * 0.5 for i in range(19)]
    boll = BollingerAgent("bollinger-1", 1000.0, params={"n": 20, "cooldown": 0})
    assert [o.side for o in decide(boll, candles(calm + [95]))] == ["buy"]
    assert [o.side for o in decide(boll, candles(calm + [105]), held=1.0)] == ["sell"]
    closes = [100.0] * 20
    cmf = ChaikinAgent("chaikin-1", 1000.0, params={"n": 20, "cooldown": 0})
    near_high = candles(closes, highs=[101] * 20, lows=[90] * 20)  # every close near the top
    assert [o.side for o in decide(cmf, near_high)] == ["buy"]
    near_low = candles(closes, highs=[110] * 20, lows=[99] * 20)
    assert [o.side for o in decide(cmf, near_low, held=1.0)] == ["sell"]


def test_courses_3_and_4_simulator_and_null_tests():
    idx = [i * DAY for i in range(6)]
    px = pd.DataFrame({"A": [10, 10, 11, 12, 12, 13], "B": [10, 9, 9, 9, 9, 9]}, index=idx, dtype=float)
    sig = pd.DataFrame({"A": [1, 0, 0, 0, -1, 0], "B": [1, 0, 0, 0, 0, 0]}, index=idx)
    pref = pd.DataFrame({"A": [2.0] * 6, "B": [1.0] * 6}, index=idx)
    eq = bs.simulate(px, sig, pref, max_positions=1, cash=100.0, slippage=0.0)
    assert eq.iloc[0] == pytest.approx(100.0) and eq.iloc[3] == pytest.approx(120.0)
    assert eq.iloc[4] == pytest.approx(120.0) and eq.iloc[5] == pytest.approx(120.0)  # sold at 12, cash after
    rng = np.random.default_rng(0)
    big = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (300, 8)), axis=0)),
                       index=[i * DAY for i in range(300)], columns=list("ABCDEFGH"))
    spy = big.mean(axis=1)
    t = bs.white_noise_test(big, bs.bollinger_signal(big), bs.rolling_sharpe(big), spy, runs=20)
    assert len(t.runs) == 20 and 0 <= t.percentile <= 1 and "beats" in t.summary()
    b = bs.bootstrap_test(big, bs.macd_signal(big), bs.rolling_sharpe(big), spy, runs=5)
    assert len(b.runs) == 5


def test_course_5_events_labels_and_uniqueness():
    lp = pd.Series(np.log([100, 101, 102, 104, 103, 99, 98, 100, 106]), index=range(9))
    ev = cusum_events(lp, 0.03)
    assert list(ev) == [3, 5, 8]
    close = pd.Series([100, 101, 103, 106, 104, 100, 99, 101, 108], index=range(9), dtype=float)
    lab = triple_barrier(close, pd.Index([0, 3, 4]), pd.Series(0.05, index=close.index), horizon=4)
    assert (lab.loc[0, "label"], lab.loc[0, "end"]) == (1, 3)          # +6% on day 3: profit take
    assert (lab.loc[3, "label"], lab.loc[3, "end"]) == (-1, 5)         # -5.8% on day 5: stop
    assert (lab.loc[4, "label"], lab.loc[4, "end"]) == (1, 8)          # neither: time limit, up
    u = average_uniqueness(pd.DataFrame({"end": [2, 3]}, index=[0, 1]), pd.Index(range(5)))
    assert u.loc[0] == pytest.approx((1 + 0.5 + 0.5) / 3) and u.loc[1] == pytest.approx((0.5 + 0.5 + 1) / 3)


def test_the_curriculum_and_a_report_card(tmp_path):
    assert set(COURSES) == {1, 2, 3, 4, 5}
    from cryptoarena.arena.backtest import load_tape
    from cryptoarena.arena.survival import SurvivalConfig
    from cryptoarena.cli import build_agents
    from test_backtest import write_tape
    write_tape(tmp_path, bars=720 + 24 * 40 + 1)
    frames = load_tape(tmp_path)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    cards = colony_report_cards(frames, lambda: build_agents(5.0, False, ""), cfg, warmup_bars=720,
                                benchmark="BTCUSD")
    assert "🏢 colônia" in cards.index and "segurar BTCUSD" in cards.index
    assert "Sharpe" in format_cards(cards)
