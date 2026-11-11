"""Richard Wyckoff's events read from price and volume, and how agents use them."""
import math
from collections import deque

import pytest

from cryptoarena.agents.base import MarketView
from cryptoarena.agents.rules import MomentumAgent, WyckoffAgent
from cryptoarena.agents.wyckoff import NONE, read
from cryptoarena.market.candle import Candle
from cryptoarena.world.personas import persona

PRIOR_FALL = [120 - 0.5 * i for i in range(40)]
PRIOR_RISE = [80 + 0.6 * i for i in range(40)]
RANGE = [105 + 4 * math.sin(i / 3) for i in range(40)]


def bars(closes, vols=None, lows=None, highs=None, symbol="X"):
    return [Candle(symbol, i, c, highs[i] if highs else c * 1.005, lows[i] if lows else c * 0.995,
                   c, vols[i] if vols else 100.0) for i, c in enumerate(closes)]


def spring():
    base = PRIOR_FALL + RANGE
    lows = [c * 0.995 for c in base] + [103.5, 102.5, 99.0, 101, 103.5]
    return bars(base + [104, 103, 102, 101.5, 104], lows=lows)


def sow():
    return bars(PRIOR_RISE + RANGE + [104, 102, 99, 98, 97], vols=[100] * 80 + [100, 100, 250, 120, 100])


def test_the_five_events():
    assert read(spring(), 40).event == "spring" and read(spring(), 40).phase == "accumulation"
    sos = bars(PRIOR_FALL + RANGE + [108, 110, 112, 113, 114], vols=[100] * 80 + [100, 100, 300, 120, 110])
    assert (read(sos, 40).event, read(sos, 40).phase) == ("sos", "markup")
    lps = bars(PRIOR_FALL + RANGE + [112, 113, 111.5, 111.8, 112], vols=[100] * 80 + [300, 120, 60, 60, 60])
    assert read(lps, 40).event == "lps"
    highs = [c * 1.005 for c in PRIOR_RISE + RANGE] + [107, 108, 112.5, 106, 106.5]
    ut = bars(PRIOR_RISE + RANGE + [106, 107, 106, 105, 106], vols=[100] * 80 + [100, 100, 200, 100, 100],
              highs=highs)
    assert (read(ut, 40).event, read(ut, 40).phase) == ("upthrust", "distribution")
    r = read(sow(), 40)
    assert (r.event, r.phase) == ("sow", "markdown") and r.score < 0 < read(spring(), 40).score


def test_no_read_without_a_range_or_enough_history():
    assert read(spring()[:60], 40) is NONE                       # too short
    trend = bars([100 * 1.01 ** i for i in range(90)])
    assert read(trend, 40) is NONE                               # a trend is not a range


def view_of(candles, symbol="X", step=500):
    last = candles[-1]
    return MarketView(candles={symbol: last}, history={symbol: deque(candles)},
                      prices={symbol: last.close}, step=step)


def test_the_lens_sells_a_sign_of_weakness_and_refuses_to_buy_into_it():
    cs = sow()
    agent = MomentumAgent("momentum-1", 1000.0, params={"wyckoff": 1.0, "wyckoff_range": 40,
                                                        "trend_filter": 0, "market_gate": 0,
                                                        "rank_top": 0, "lookback": 5,
                                                        "entry_threshold": -1.0, "cooldown": 0})
    agent.history = {"X": deque(cs, maxlen=720)}
    agent.wallet.positions["X"] = 2.0
    orders = agent.decide(view_of(cs))
    assert [(o.side, o.reason) for o in orders] == [("sell", "wyckoff sow")]
    agent.params["wyckoff"] = 0.0                                 # without the lens it would buy
    assert any(o.side == "buy" for o in agent.decide(view_of(cs)))
    assert MomentumAgent("m", 1.0).params["wyckoff"] == 0.0       # off unless asked
    agent.set_params({"wyckoff": 0.5})
    assert agent.get_params()["wyckoff"] == 0.5                  # it survives a save and restore


def test_walter_buys_the_spring_and_sells_the_sign_of_weakness():
    walter = WyckoffAgent("wyckoff-1", 1000.0, params={"wyckoff_range": 40, "cooldown": 0})
    cs = spring()
    walter.history = {"X": deque(cs, maxlen=720)}
    buy = walter.decide(view_of(cs))
    assert [(o.side, o.reason) for o in buy] == [("buy", "wyckoff spring (accumulation)")]
    cs = sow()
    walter.history = {"X": deque(cs, maxlen=720)}
    walter.wallet.positions["X"] = 1.0
    assert [o.side for o in walter.decide(view_of(cs, step=600))] == ["sell"]
    assert persona("wyckoff-1").name == "Walter Volume"
    assert pytest.approx(walter.params["stop_trail"]) == 0.08
