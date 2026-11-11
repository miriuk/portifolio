from cryptoarena.learning.memory import TradeJournal


def test_reinforcement_instead_of_duplicates(tmp_path):
    j = TradeJournal(tmp_path / "m.db")
    lesson = "episode 1: lost -300 trading in 'crash' regime — reduce activity there."
    j.add_lesson("a", 1, lesson, regime="crash")
    j.add_lesson("a", 2, "episode 2: lost -100 trading in 'crash' regime — reduce activity there.",
                 regime="crash")
    rows = j._conn.execute(
        "SELECT importance FROM lessons WHERE agent_id='a'").fetchall()
    assert len(rows) == 1            # reinforced, not duplicated
    assert rows[0][0] == 1.5
    j.close()


def test_regime_matched_retrieval(tmp_path):
    j = TradeJournal(tmp_path / "m.db")
    j.add_lesson("a", 1, "lesson about crash", regime="crash")
    j.add_lesson("a", 2, "lesson about bull", regime="bull")
    j.add_lesson("a", 3, "generic lesson", regime="")
    top = j.lessons_for("a", limit=1, regime="crash")
    assert top == ["lesson about crash"]  # boosted above newer memories
    j.close()


def test_decay_and_pruning(tmp_path):
    j = TradeJournal(tmp_path / "m.db")
    j.add_lesson("a", 1, "fading memory", importance=0.3)
    j.add_lesson("a", 1, "strong memory", importance=3.0)
    pruned = j.decay_lessons("a", factor=0.5, prune_below=0.25)
    assert pruned == 1
    assert j.lessons_for("a") == ["strong memory"]
    j.close()


def test_migration_of_old_db(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL,
        episode INTEGER NOT NULL, lesson TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("INSERT INTO lessons (agent_id, episode, lesson) VALUES ('a', 1, 'old')")
    conn.commit()
    conn.close()
    j = TradeJournal(db)   # must add regime/importance columns without losing data
    assert j.lessons_for("a") == ["old"]
    j.add_lesson("a", 2, "new", regime="bull")
    j.close()
