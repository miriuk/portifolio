from cryptoarena.agents.rules import MomentumAgent
from cryptoarena.arena.tournament import run_tournament
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.learning.reflection import EpisodeStats


def test_record_and_read_equity(tmp_path):
    j = TradeJournal(tmp_path / "j.db")
    j.record_equity("a", 1, 0, 10_000.0)
    j.record_equity("a", 1, 1, 10_050.0)
    rows = j._conn.execute(
        "SELECT episode, step, equity FROM equity_snapshots WHERE agent_id='a' ORDER BY step"
    ).fetchall()
    assert rows == [(1, 0, 10_000.0), (1, 1, 10_050.0)]
    j.close()


def test_record_episode_summary_upserts(tmp_path):
    j = TradeJournal(tmp_path / "j.db")
    stats = EpisodeStats("a", 1, start_equity=10_000.0, end_equity=10_500.0,
                         n_trades=3, n_wins=2, n_losses=1, max_drawdown=0.05)
    j.record_episode_summary(stats, halted=False)
    row = j._conn.execute(
        "SELECT end_equity, n_trades, halted FROM episode_summary "
        "WHERE agent_id='a' AND episode=1"
    ).fetchone()
    assert row == (10_500.0, 3, 0)

    # re-recording the same episode updates in place, not duplicates
    stats.end_equity = 10_600.0
    j.record_episode_summary(stats, halted=True)
    rows = j._conn.execute(
        "SELECT end_equity, halted FROM episode_summary WHERE agent_id='a' AND episode=1"
    ).fetchall()
    assert rows == [(10_600.0, 1)]
    j.close()


def test_tournament_persists_dashboard_data(tmp_path):
    """After a real run, the DB alone (no in-memory state) has everything
    a separate dashboard process needs to render equity curves + leaderboard."""
    journal = TradeJournal(tmp_path / "arena.db")
    agents = [MomentumAgent("m1", 10_000.0)]
    run_tournament(agents, journal, episodes=2, steps_per_episode=24 * 3,
                   seed=5, verbose=False)
    journal.close()

    # fresh connection, as the dashboard would open it
    reader = TradeJournal(tmp_path / "arena.db")
    n_equity = reader._conn.execute(
        "SELECT COUNT(*) FROM equity_snapshots WHERE agent_id='m1'").fetchone()[0]
    n_episodes = reader._conn.execute(
        "SELECT COUNT(*) FROM episode_summary WHERE agent_id='m1'").fetchone()[0]
    assert n_equity == 24 * 3 * 2   # steps_per_episode * episodes
    assert n_episodes == 2
    reader.close()
