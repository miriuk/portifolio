from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    episode INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    reason TEXT,
    regime TEXT,
    pnl REAL              -- realized pnl, filled on closing trades
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    episode INTEGER NOT NULL,
    lesson TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    params TEXT NOT NULL,      -- JSON of tunable parameters
    generation INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades (agent_id, episode);
"""


@dataclass
class TradeRecord:
    agent_id: str
    episode: int
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    timestamp: int
    reason: str = ""
    regime: str = ""
    pnl: float | None = None


class TradeJournal:
    """Persistent memory: every trade, every lesson, every parameter set.

    This is what lets agents 'learn with errors and wins' across episodes —
    the journal survives restarts, so learning is cumulative.
    """

    def __init__(self, db_path: str | Path = "arena.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_trade(self, record: TradeRecord) -> None:
        d = asdict(record)
        self._conn.execute(
            """INSERT INTO trades (agent_id, episode, symbol, side, quantity,
               price, fee, timestamp, reason, regime, pnl)
               VALUES (:agent_id, :episode, :symbol, :side, :quantity,
               :price, :fee, :timestamp, :reason, :regime, :pnl)""",
            d,
        )
        self._conn.commit()

    def trades_for(self, agent_id: str, episode: int | None = None) -> list[TradeRecord]:
        q = "SELECT agent_id, episode, symbol, side, quantity, price, fee, timestamp, reason, regime, pnl FROM trades WHERE agent_id = ?"
        args: list = [agent_id]
        if episode is not None:
            q += " AND episode = ?"
            args.append(episode)
        rows = self._conn.execute(q + " ORDER BY id", args).fetchall()
        return [TradeRecord(*row) for row in rows]

    def add_lesson(self, agent_id: str, episode: int, lesson: str) -> None:
        self._conn.execute(
            "INSERT INTO lessons (agent_id, episode, lesson) VALUES (?, ?, ?)",
            (agent_id, episode, lesson),
        )
        self._conn.commit()

    def lessons_for(self, agent_id: str, limit: int = 12) -> list[str]:
        rows = self._conn.execute(
            "SELECT lesson FROM lessons WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [r[0] for r in reversed(rows)]

    def save_params(self, agent_id: str, params: dict, generation: int = 0) -> None:
        self._conn.execute(
            """INSERT INTO agent_state (agent_id, params, generation) VALUES (?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET params = excluded.params,
               generation = excluded.generation""",
            (agent_id, json.dumps(params, sort_keys=True), generation),
        )
        self._conn.commit()

    def load_params(self, agent_id: str) -> tuple[dict, int] | None:
        row = self._conn.execute(
            "SELECT params, generation FROM agent_state WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0]), row[1]
