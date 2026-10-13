"""Splitting the PM's money by risk: equal, inverse volatility, HRP."""
import numpy as np
import pytest

from cryptoarena.agents.base import TradingAgent
from cryptoarena.arena.desk import PMBook
from cryptoarena.market.candle import Candle
from cryptoarena.portfolio.allocation import (hrp_weights, inverse_vol_weights, seriation, split)


def returns(seed=0, t=500):
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 0.01, t)
    b = a + rng.normal(0, 0.002, t)             # b is really a again
    c = rng.normal(0, 0.03, t)                  # a wild, unrelated name
    return np.column_stack([a, b, c])


def test_inverse_vol_gives_the_calm_names_more():
    w = inverse_vol_weights(returns())
    assert w.sum() == pytest.approx(1.0)
    assert w[2] < w[0] and w[2] < w[1]


def test_hrp_lets_two_copies_of_one_bet_share_a_slice():
    r = returns()
    order = seriation(np.sqrt((1 - np.corrcoef(r, rowvar=False)) / 2))
    assert abs(order.index(0) - order.index(1)) == 1          # the twins sit together
    w = hrp_weights(r)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    ivar = 1 / r.var(axis=0)
    ivar /= ivar.sum()
    # per-name inverse variance counts the twins as two bets; HRP splits
    # first between the twins' cluster and the wild name, so the wild one keeps more
    assert w[2] > ivar[2]
    assert w[0] == pytest.approx(w[1], rel=0.1)
    four = np.column_stack([r, np.random.default_rng(1).normal(0, 0.01, len(r))])
    w4 = hrp_weights(four)
    assert w4[3] > w4[0] and w4[3] > w4[1]                    # the independent calm name leads


def test_split_falls_back_to_the_votes_without_history():
    votes = {"A": 0.3, "B": 0.1}
    assert split("hrp", ["A", "B"], None, votes) == pytest.approx({"A": 0.75, "B": 0.25})
    assert split("equal", ["A", "B"], None, votes) == {"A": 0.5, "B": 0.5}
    assert split("votes", ["A", "B"], returns()[:, :2], votes) == pytest.approx({"A": 0.75, "B": 0.25})
    with pytest.raises(ValueError):
        split("magic", ["A", "B"], returns()[:, :2], votes)


class Holder(TradingAgent):
    def decide(self, view):
        return []


def test_the_pm_keeps_the_votes_total_and_names_but_splits_by_risk():
    rng = np.random.default_rng(3)
    agents = [Holder("a-1", 100.0), Holder("b-1", 100.0)]
    calm, wild = 100.0, 100.0
    for t in range(200):
        calm *= 1 + rng.normal(0, 0.005)
        wild *= 1 + rng.normal(0, 0.04)
        for a in agents:
            a.observe([Candle("CALM", t, calm, calm, calm, calm, 1.0),
                       Candle("WILD", t, wild, wild, wild, wild, 1.0)])
    prices = {"CALM": calm, "WILD": wild}
    agents[0].wallet.positions["WILD"] = 60.0 / wild            # the votes lean on the wild one
    agents[0].wallet.cash -= 60.0
    agents[1].wallet.positions["CALM"] = 20.0 / calm
    agents[1].wallet.cash -= 20.0
    votes = PMBook(200.0).target_weights(agents, prices)
    assert votes == pytest.approx({"WILD": 0.3, "CALM": 0.1})
    pm = PMBook(200.0, weighting="inverse_vol", lookback=150)
    t = pm.target_weights(agents, prices)
    assert sum(t.values()) == pytest.approx(0.4)               # same total invested
    assert set(t) == {"WILD", "CALM"} and t["CALM"] > t["WILD"]
    again = PMBook.load(pm.dump())
    assert (again.weighting, again.lookback) == ("inverse_vol", 150)
