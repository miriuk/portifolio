import json

import pandas as pd

from cryptoarena.world.render import build_state, market_state, render_world


def test_market_state_change_and_regime():
    rows = []
    for step in range(30):
        rows.append(dict(episode=1, step=step, symbol="BTCUSDT", close=100.0 + step, regime="bull"))
        rows.append(dict(episode=1, step=step, symbol="ETHUSDT", close=50.0, regime="chop"))
    m = market_state(pd.DataFrame(rows))
    btc = next(s for s in m["symbols"] if s["symbol"] == "BTCUSDT")
    assert btc["close"] == 129.0
    assert abs(btc["change"] - (129 / 105 - 1)) < 1e-4     # last 24 bars, not the whole tape
    assert m["regime"] in {"bull", "chop"}


def test_build_state_and_render_inject_json():
    summary = pd.DataFrame([dict(agent_id="momentum-1", episode=2, start_equity=1000.0,
                                 end_equity=1010.0, n_trades=1, n_wins=1, n_losses=0,
                                 n_stop_losses=0, fees=0.1, max_drawdown=0.0, halted=0)])
    survival = pd.DataFrame([dict(day=0, agent_id="momentum-1", event="born", equity=1000.0,
                                  parent_id=None, generation=0, strategy="momentum", detail=""),
                             dict(day=2, agent_id="momentum-1", event="cloned", equity=1005.0,
                                  parent_id=None, generation=0, strategy="momentum",
                                  detail="child momentum-2 with 50")])
    state = build_state({"summary": summary, "survival": survival}, running=True)
    assert state["day"] == 2 and state["running"] and state["mode"] == "survival"
    assert state["colony"] == {"alive": 1, "total": 1, "equity": 1010.0}
    assert state["agents"][0]["agent_id"] == "momentum-1"
    assert state["events"][-1]["event"] == "cloned"

    html = render_world(state)
    assert "/*__STATE__*/null" not in html
    start = html.index("const STATE = ") + len("const STATE = ")
    end = html.index(";\n", start)
    assert json.loads(html[start:end]) == state


def test_party_state_marks_the_evening_of_the_party():
    from cryptoarena.world.render import party_state
    surv = pd.DataFrame([
        dict(day=7, agent_id="momentum-1", event="party", equity=0.05, parent_id=None,
             generation=0, strategy="momentum", detail="week 1: +5.0%"),
        dict(day=7, agent_id="meanrev-1", event="party", equity=0.04, parent_id=None,
             generation=0, strategy="meanreversion", detail="week 1: +4.0%"),
        dict(day=7, agent_id="momentum-1", event="employee_of_week", equity=0.05,
             parent_id=None, generation=0, strategy="momentum", detail="week 1: +5.0%"),
    ])
    tonight = party_state(surv, day=7)
    assert tonight["active"] and tonight["week"] == 1 and tonight["employee"] == "momentum-1"
    assert [w["agent_id"] for w in tonight["winners"]] == ["momentum-1", "meanrev-1"]
    later = party_state(surv, day=9)
    assert later["active"] is False and later["employee"] == "momentum-1"   # frame stays up


def test_senior_state_is_the_latest_pick():
    from cryptoarena.world.render import senior_state
    surv = pd.DataFrame([
        dict(day=7, agent_id="momentum-1", event="senior", equity=0.02, parent_id=None,
             generation=0, strategy="momentum", detail="+2.0% since day 0"),
        dict(day=14, agent_id="voltarget-1", event="senior", equity=0.09, parent_id=None,
             generation=0, strategy="voltarget", detail="+9.0% since day 0"),
    ])
    assert senior_state(surv) == {"agent_id": "voltarget-1", "ret": 0.09, "day": 14}
    assert senior_state(pd.DataFrame()) is None


def test_render_escapes_script_terminators():
    state = build_state({})
    state["events"] = [{"day": 1, "agent_id": "x", "event": "died", "detail": "</script>"}]
    assert "</script>" not in render_world(state).split("const STATE = ")[1].split("\n")[0]
