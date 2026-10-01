"""The desk feed: one line per thing that happened, newest first."""
import pandas as pd

from cryptoarena.world.feed import build_feed, render_feed


def test_the_feed_orders_a_day_trades_then_desk_then_the_chief_and_escapes_html():
    trades = pd.DataFrame([
        dict(agent_id="momentum-1", episode=4, symbol="NVDA", side="buy", quantity=0.16,
             price=227.4, timestamp=1790640000, reason="momentum +4.49%"),
        dict(agent_id="meanrev-1", episode=3, symbol="AAPL", side="sell", quantity=0.1,
             price=330.0, timestamp=1790553600, reason=""),
    ])
    events = pd.DataFrame([
        dict(day=4, agent_id="chief", event="chief_note", detail="Colônia <b>$1,321</b>"),
        dict(day=4, agent_id="trend-1", event="vetoed",
             detail="desk: buy NVDA refused: NVDA at 20% of the desk (cap 20%)"),
        dict(day=4, agent_id="pm", event="pm_trade", detail="desk: buy NVDA 120.00 at 227.40"),
        dict(day=4, agent_id="momentum-2", event="survived", detail="cost 0.03"),   # not on the feed
    ])
    rows = build_feed(trades, events)
    assert [r["tag"] for r in rows] == ["CHIEF", "PM", "RISK", "MOMENTUM-1", "MEANREV-1"]
    assert rows[2]["text"].startswith("trend-1 · buy NVDA refused") and rows[2]["tone"] == "red"
    assert rows[3]["text"] == "buy NVDA 36.38 · momentum +4.49%"
    html = render_feed(rows)
    assert "<b>" not in html and "&lt;b&gt;" in html


def test_an_empty_journal_says_so():
    assert "nothing on the feed" in render_feed(build_feed(pd.DataFrame(), pd.DataFrame()))
