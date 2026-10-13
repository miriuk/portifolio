"""Course 7: the great traders' rules, tested like everything else."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.arena import booksim as bs
from cryptoarena.learning import wizards as w

DAY = 86400


def frames(n=700, k=6, seed=0):
    rng = np.random.default_rng(seed)
    out = {}
    for j in range(k):
        c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
        o = np.r_[c[0], c[:-1]]
        out[f"S{j}"] = pd.DataFrame({"timestamp": 1_500_000_000 + np.arange(n) * DAY, "open": o,
                                     "high": np.maximum(o, c) * 1.005, "low": np.minimum(o, c) * 0.995,
                                     "close": c, "volume": rng.lognormal(10, 0.3, n)})
    return out


def test_every_master_has_a_path_lessons_and_a_rule_or_none():
    keys = {p["key"] for p in w.PROFILES}
    assert {"marcus", "schwartz", "kotegawa", "ptj", "turtles", "minervini"} <= keys
    for p in w.PROFILES:
        assert p["path"] and p["lessons"] and p["books"]
    p = w.panels(frames())
    for name, (_, fn) in w.RULES.items():
        sig, pref, risk = fn(p)
        assert sig.shape == p["close"].shape and set(np.unique(sig.to_numpy())) <= {-1, 0, 1}, name
        assert isinstance(risk, dict)


def test_risk_rules_in_the_simulator():
    idx = [i * DAY for i in range(6)]
    px = pd.DataFrame({"A": [100, 104, 96, 91, 95, 99.0]}, index=idx)
    buy = pd.DataFrame({"A": [1, 0, 0, 0, 0, 0]}, index=idx)
    pref = pd.DataFrame({"A": [1.0] * 6}, index=idx)
    stop = bs.simulate(px, buy, pref, max_positions=1, cash=100.0, slippage=0.0, stop_loss=0.08)
    assert stop.iloc[-1] == pytest.approx(91.0)                   # out at 91, below 92
    trail = bs.simulate(px, buy, pref, max_positions=1, cash=100.0, slippage=0.0, trail=0.05)
    assert trail.iloc[-1] == pytest.approx(96.0)                  # 104 -> 96 is more than 5% off the high
    held = bs.simulate(px, buy, pref, max_positions=1, cash=100.0, slippage=0.0, max_hold=2)
    assert held.iloc[-1] == pytest.approx(96.0)
    nxt = bs.simulate(px, buy, pref, max_positions=1, cash=100.0, slippage=0.0,
                      exec_prices=px.shift(-1))                    # filled at the next row's price
    assert nxt.iloc[1] == pytest.approx(100.0)


def test_shuffled_entries_keep_the_count_and_avoid_exit_days():
    rng = np.random.default_rng(1)
    sig = pd.DataFrame({"A": [1, 0, -1, 0, 1, 0, -1, -1, 0, 0]})
    out = w._shuffled_entries(sig, rng)
    assert (out["A"] == 1).sum() == 2 and (out["A"] == -1).sum() == 3
    assert not ((out["A"] == 1) & (sig["A"] == -1)).any()


def test_the_exams_run():
    p = w.panels(frames())
    sc = w.timing_exam(p, "S0", "ptj200", shuffles=5)
    assert 0 <= sc.luck_pct <= 1 and 0 <= sc.in_market <= 1 and sc.hold_cagr == sc.hold_cagr
    bench = p["close"]["S1"]
    pk = w.picking_exam(p, "kotegawa10", bench, "test", max_positions=3, shuffles=3)
    assert pk.universe_cagr == pk.universe_cagr
    r = w.risk_exam(p, bench, runs=2, rate=0.05)
    assert set(r) == {"segurar 20 dias", "stop 8% + trailing 15%", "só stop 8%, 60 dias"}
    assert all(len(v) == 2 for v in r.values())


def test_the_office_quotes_the_masters():
    from cryptoarena.world.render import build_state
    st = build_state({})
    assert any(x["name"] == "Michael Marcus" for x in st["wisdom"])
