import pytest

from cryptoarena.arena import background
from cryptoarena.arena.background import RunConfig, start_tournament
from cryptoarena.learning.memory import TradeJournal


def test_background_run_writes_journal(tmp_path):
    db = tmp_path / "arena.db"
    state = start_tournament(RunConfig(db_path=str(db), episodes=2, steps=24, seed=1))
    state.thread.join(timeout=60)

    assert not state.running
    assert state.error is None
    assert state.finished_at is not None

    reader = TradeJournal(db)
    n_episodes = reader._conn.execute(
        "SELECT COUNT(DISTINCT episode) FROM episode_summary").fetchone()[0]
    reader.close()
    assert n_episodes == 2


def test_only_one_run_at_a_time(tmp_path):
    db = tmp_path / "arena.db"
    state = start_tournament(RunConfig(db_path=str(db), episodes=1, steps=24 * 30, seed=1))
    if state.running:
        with pytest.raises(RuntimeError):
            start_tournament(RunConfig(db_path=str(db), episodes=1, steps=24))
    state.thread.join(timeout=60)
    assert background.current_run() is state
