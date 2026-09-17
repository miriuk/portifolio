import pandas as pd

from cryptoarena.world.needs import compute_vitals

EMPTY = pd.DataFrame()


def _summary(rows):
    cols = ["agent_id", "episode", "start_equity", "end_equity", "n_trades", "n_wins",
            "n_losses", "n_stop_losses", "fees", "max_drawdown", "halted"]
    return pd.DataFrame(rows, columns=cols)


def _lessons(rows):
    return pd.DataFrame(rows, columns=["agent_id", "episode", "lesson", "regime", "importance"])


def _survival(rows):
    return pd.DataFrame(rows, columns=["day", "agent_id", "event", "equity", "parent_id",
                                       "generation", "strategy", "detail"])


def test_no_data_means_no_agents():
    assert compute_vitals(EMPTY, EMPTY, EMPTY, EMPTY) == []


def test_winner_is_confident_and_focused():
    summary = _summary([("momentum-1", d, 1000 + 12 * (d - 1), 1000 + 12 * d, 2, 2, 0, 0,
                         0.5, 0.01, 0) for d in (1, 2, 3)])
    lessons = _lessons([("momentum-1", 3, "lean into this setup", "bull", 2.0)])
    surv = _survival([(0, "momentum-1", "born", 1000, None, 0, "momentum", ""),
                      (3, "momentum-1", "target_hit", 1036, None, 0, "momentum", "streak 3")])
    (v,) = compute_vitals(summary, EMPTY, lessons, surv)
    assert v.alive and v.mood == "euphoric" and v.activity == "celebrating"
    assert v.streak == 3 and v.misses == 0
    assert v.stress < 0.3 and v.focus > 0.6
    assert abs(v.window_return - 0.036) < 0.01


def test_loser_near_death_line_panics():
    summary = _summary([("meanrev-1", 1, 1000, 900, 6, 1, 5, 3, 2, 0.12, 0),
                        ("meanrev-1", 2, 900, 780, 7, 1, 6, 3, 2, 0.15, 0),
                        ("meanrev-1", 3, 780, 660, 5, 0, 5, 2, 2, 0.16, 0)])
    surv = _survival([(0, "meanrev-1", "born", 1000, None, 0, "meanreversion", "")])
    (v,) = compute_vitals(summary, EMPTY, EMPTY, surv)
    assert v.alive
    assert v.stress > 0.75 and v.mood == "panicking" and v.activity == "pacing"
    assert v.misses == 3
    assert v.energy < 0.6  # 18 trades in 3 days at 16% drawdown is tiring


def test_dead_agents_stay_dead_and_children_know_their_parent():
    summary = _summary([("breakout-1", 1, 1000, 1010, 1, 1, 0, 0, 0.1, 0.0, 0),
                        ("breakout-2", 1, 100, 101, 0, 0, 0, 0, 0.0, 0.0, 0)])
    surv = _survival([(0, "breakout-1", "born", 1000, None, 0, "breakout", ""),
                      (1, "breakout-2", "born", 100, "breakout-1", 1, "breakout", ""),
                      (1, "breakout-2", "died", 40, "breakout-1", 1, "breakout", "kill switch")])
    by_id = {v.agent_id: v for v in compute_vitals(summary, EMPTY, EMPTY, surv)}
    assert by_id["breakout-2"].alive is False and by_id["breakout-2"].mood == "dead"
    assert by_id["breakout-2"].parent_id == "breakout-1" and by_id["breakout-2"].generation == 1
    assert by_id["breakout-1"].alive and by_id["breakout-1"].parent_id is None
    assert (by_id["breakout-1"].role, by_id["breakout-2"].role) == ("specialist", "intern")


def test_intern_remembers_its_mentor_and_tip():
    summary = _summary([("momentum-2", d, 200, 199, 1, 0, 1, 0, 0.1, 0.01, 0) for d in (41, 42, 43)])
    surv = _survival([(40, "momentum-2", "born", 200, "momentum-1", 1, "momentum", ""),
                      (43, "momentum-2", "consulted", 0.0, "momentum-1", 1, "momentum",
                       "day 2: barely traded — too passive; loosen entries.")])
    (v,) = compute_vitals(summary, EMPTY, EMPTY, surv)
    assert v.role == "intern" and v.mentor == "momentum-1" and "too passive" in v.tip
    assert v.misses == 3   # counted from the day it was hired, not from day 1


def test_last_trade_feeds_chatter_fields():
    summary = _summary([("momentum-1", 1, 1000, 1000, 1, 0, 0, 0, 0.1, 0.0, 0)])
    trades = pd.DataFrame([dict(id=2, agent_id="momentum-1", episode=1, symbol="ETHUSDT",
                                side="buy", quantity=0.1, price=3000.0, fee=0.3, timestamp=5,
                                reason="momentum +2.40%", regime="bull", pnl=None),
                           dict(id=1, agent_id="momentum-1", episode=1, symbol="BTCUSDT",
                                side="sell", quantity=0.01, price=60000.0, fee=0.6, timestamp=2,
                                reason="momentum faded -1.20%", regime="chop", pnl=-3.0)])
    (v,) = compute_vitals(summary, trades, EMPTY, EMPTY)
    assert (v.last_symbol, v.last_side, v.regime) == ("ETHUSDT", "buy", "bull")
    assert "momentum" in v.last_reason
    assert v.to_dict()["mood"] in {"calm", "confident"}
