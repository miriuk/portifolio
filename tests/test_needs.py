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


def test_dismissal_worries_and_motivates_the_ones_who_stay():
    summary = _summary([("momentum-2", d, 200, 200, 1, 0, 0, 0, 0.1, 0.0, 0) for d in (8, 9, 10)]
                       + [("momentum-1", d, 1000, 1000, 1, 0, 0, 0, 0.1, 0.0, 0) for d in (8, 9, 10)])
    quiet = _survival([(0, "momentum-1", "born", 1000, None, 0, "momentum", ""),
                       (5, "momentum-2", "born", 200, "momentum-1", 1, "momentum", "")])
    shaken = pd.concat([quiet, _survival([
        (5, "meanrev-3", "born", 200, "meanrev-1", 1, "meanreversion", ""),
        (9, "meanrev-3", "died", 100, "meanrev-1", 1, "meanreversion", "below 60% of budget")])])
    before = {v.agent_id: v for v in compute_vitals(summary, EMPTY, EMPTY, quiet)}
    after = {v.agent_id: v for v in compute_vitals(summary, EMPTY, EMPTY, shaken)}
    intern_b, intern_a = before["momentum-2"], after["momentum-2"]
    assert intern_a.stress > intern_b.stress and intern_a.motivation > intern_b.motivation
    # the specialist is safe, so the news barely rattles it — but it still spurs it on
    assert after["momentum-1"].stress - before["momentum-1"].stress < intern_a.stress - intern_b.stress
    assert after["momentum-1"].motivation > before["momentum-1"].motivation


def test_party_and_frame_lift_ego_and_change_mood():
    summary = _summary([("breakout-1", d, 1000 + 8 * (d - 1), 1000 + 8 * d, 2, 2, 0, 0, 0.2,
                         0.01, 0) for d in (5, 6, 7)])
    surv = _survival([(0, "breakout-1", "born", 1000, None, 0, "breakout", "")]
                     + [(d, "breakout-1", "target_hit", 1000 + 8 * d, None, 0, "breakout",
                         f"streak {d - 4}") for d in (5, 6, 7)]
                     + [(7, "breakout-1", "party", 0.056, None, 0, "breakout", "week 1: +5.6%"),
                      (7, "breakout-1", "employee_of_week", 0.056, None, 0, "breakout",
                       "week 1: +5.6%")])
    plain = compute_vitals(summary, EMPTY, EMPTY, surv.iloc[:1])[0]
    star = compute_vitals(summary, EMPTY, EMPTY, surv)[0]
    assert star.parties == 1 and star.awards == 1
    assert star.ego > plain.ego + 0.3 and star.motivation > plain.motivation
    assert star.mood == "proud" and star.activity == "celebrating"


def test_immunity_calms_an_intern_near_the_line_and_being_spared_shakes_it():
    # flat at 70% of its budget: close to the line, no fresh losses
    summary = _summary([("meanrev-3", d, 140, 140, 1, 0, 1, 0, 0.1, 0.02, 0) for d in (8, 9, 10)])
    base = _survival([(5, "meanrev-3", "born", 200, "meanrev-1", 1, "meanreversion", "")])
    immune = pd.concat([base, _survival([
        (7, "meanrev-3", "party", 0.04, "meanrev-1", 1, "meanreversion", "week 1: +4.0%"),
        (7, "meanrev-3", "immune", 0.04, "meanrev-1", 1, "meanreversion", "until day 14")])])
    spared = pd.concat([immune, _survival([
        (10, "meanrev-3", "spared", 140, "meanrev-1", 1, "meanreversion", "immunity until day 14")])])
    exposed = compute_vitals(summary, EMPTY, EMPTY, base)[0]
    shielded = compute_vitals(summary, EMPTY, EMPTY, immune)[0]
    saved = compute_vitals(summary, EMPTY, EMPTY, spared)[0]
    assert exposed.immune_until == 0 and shielded.immune_until == 14
    assert shielded.stress < exposed.stress            # 65% of budget, but safe this week
    assert saved.spared == 1
    assert saved.stress > shielded.stress and saved.motivation > shielded.motivation
    # immunity that already expired is not immunity
    stale = pd.concat([base, _survival([(1, "meanrev-3", "immune", 0, "meanrev-1", 1,
                                         "meanreversion", "until day 8")])])
    assert compute_vitals(summary, EMPTY, EMPTY, stale)[0].immune_until == 0


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
