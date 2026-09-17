import pandas as pd
import pytest

pytest.importorskip("streamlit")

from cryptoarena.dashboard import leaderboard, lineage_dot  # noqa: E402


def test_lineage_dot_marks_parents_and_deaths():
    events = pd.DataFrame([
        dict(day=0, agent_id="momentum-1", event="born", equity=1000.0, parent_id=None,
             generation=0, strategy="momentum", detail=""),
        dict(day=14, agent_id="momentum-2", event="born", equity=120.0, parent_id="momentum-1",
             generation=1, strategy="momentum", detail=""),
        dict(day=30, agent_id="momentum-2", event="died", equity=50.0, parent_id="momentum-1",
             generation=1, strategy="momentum", detail="below 60% of budget"),
        dict(day=30, agent_id="momentum-1", event="survived", equity=1234.0, parent_id=None,
             generation=0, strategy="momentum", detail=""),
    ])
    dot = lineage_dot(events)
    assert dot.startswith("digraph lineage")
    assert '"momentum-1" -> "momentum-2"' in dot
    assert "let go · day 30" in dot                # the dismissed are labelled, gently
    assert dot.count('fillcolor="#f7931a"') == 1   # only the living founder keeps its color
    assert "gen 0 · 1,234" in dot                  # living nodes show their latest equity


def test_leaderboard_compounds_daily_returns():
    summary = pd.DataFrame([
        dict(agent_id="a", episode=1, start_equity=100.0, end_equity=110.0, n_trades=1,
             n_wins=1, n_losses=0, max_drawdown=0.0, halted=0),
        dict(agent_id="a", episode=2, start_equity=110.0, end_equity=99.0, n_trades=1,
             n_wins=0, n_losses=1, max_drawdown=0.1, halted=0),
    ])
    board = leaderboard(summary)
    assert board.loc[0, "episodes"] == 2
    assert abs(board.loc[0, "return"] - (-0.01)) < 1e-9
    assert board.loc[0, "win_rate"] == 0.5
