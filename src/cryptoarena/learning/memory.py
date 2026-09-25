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
    regime TEXT DEFAULT '',
    importance REAL DEFAULT 1.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    params TEXT NOT NULL,      -- JSON of tunable parameters
    generation INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    episode INTEGER NOT NULL,
    step INTEGER NOT NULL,
    equity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS episode_summary (
    agent_id TEXT NOT NULL,
    episode INTEGER NOT NULL,
    start_equity REAL NOT NULL,
    end_equity REAL NOT NULL,
    n_trades INTEGER NOT NULL,
    n_wins INTEGER NOT NULL,
    n_losses INTEGER NOT NULL,
    n_stop_losses INTEGER NOT NULL,
    fees REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    halted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, episode)
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    episode INTEGER NOT NULL,
    step INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    close REAL NOT NULL,
    regime TEXT DEFAULT '',
    PRIMARY KEY (episode, step, symbol)
);
CREATE TABLE IF NOT EXISTS survival_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    event TEXT NOT NULL,         -- born | survived | target_hit | cloned | died
    equity REAL NOT NULL,
    parent_id TEXT,
    generation INTEGER DEFAULT 0,
    strategy TEXT DEFAULT '',
    detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS colony_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,          -- JSON blob: a live colony's wallets, positions, clock…
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS source_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,         -- the X handle
    post_id TEXT NOT NULL,
    ts INTEGER NOT NULL,          -- when the post was made (unix seconds)
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,        -- +1 long, -1 short
    text TEXT DEFAULT '',
    url TEXT DEFAULT '',
    price_at REAL,                -- the price when the colony first saw the call
    resolved_ts INTEGER,
    outcome REAL,                 -- return in the call's direction, once judged
    UNIQUE (source, post_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades (agent_id, episode);
CREATE INDEX IF NOT EXISTS idx_equity_agent ON equity_snapshots (agent_id, episode, step);
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
        # WAL lets a dashboard read the DB concurrently while a run is writing to it.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(lessons)")}
        if "regime" not in cols:
            self._conn.execute("ALTER TABLE lessons ADD COLUMN regime TEXT DEFAULT ''")
        if "importance" not in cols:
            self._conn.execute("ALTER TABLE lessons ADD COLUMN importance REAL DEFAULT 1.0")
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

    def add_lesson(self, agent_id: str, episode: int, lesson: str,
                   regime: str = "", importance: float = 1.0) -> None:
        """Insert a lesson — or, if the same theme was already learned for the
        same regime, reinforce the existing one (FinMem-style promotion:
        repeated lessons decay slower instead of piling up as duplicates)."""
        # theme = the advice clause (after the em-dash), which is stable
        # across episodes; the numbers before it vary per episode
        theme = (lesson.rsplit("\u2014", 1)[-1] if "\u2014" in lesson
                 else lesson.split(":", 1)[-1]).strip()[:48]
        row = self._conn.execute(
            """SELECT id, importance FROM lessons
               WHERE agent_id = ? AND regime = ? AND lesson LIKE ?
               ORDER BY id DESC LIMIT 1""",
            (agent_id, regime, f"%{theme}%"),
        ).fetchone()
        if row is not None:
            self._conn.execute(
                "UPDATE lessons SET importance = ?, episode = ? WHERE id = ?",
                (min(row[1] + 0.5, 3.0), episode, row[0]),
            )
        else:
            self._conn.execute(
                """INSERT INTO lessons (agent_id, episode, lesson, regime, importance)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_id, episode, lesson, regime, importance),
            )
        self._conn.commit()

    def lessons_for(self, agent_id: str, limit: int = 12,
                    regime: str | None = None) -> list[str]:
        """Retrieve lessons ranked by importance, boosted when they were
        learned under the given market regime (condition-matched retrieval,
        not recency-matched)."""
        if regime:
            rows = self._conn.execute(
                """SELECT lesson FROM lessons WHERE agent_id = ?
                   ORDER BY importance + (CASE WHEN regime = ? THEN 1.0 ELSE 0 END) DESC,
                            id DESC LIMIT ?""",
                (agent_id, regime, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT lesson FROM lessons WHERE agent_id = ?
                   ORDER BY importance DESC, id DESC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()
        return [r[0] for r in reversed(rows)]

    def decay_lessons(self, agent_id: str, factor: float = 0.85,
                      prune_below: float = 0.25) -> int:
        """Fade unreinforced memories; forget the ones that stopped mattering.
        Returns how many lessons were pruned."""
        self._conn.execute(
            "UPDATE lessons SET importance = importance * ? WHERE agent_id = ?",
            (factor, agent_id),
        )
        cur = self._conn.execute(
            "DELETE FROM lessons WHERE agent_id = ? AND importance < ?",
            (agent_id, prune_below),
        )
        self._conn.commit()
        return cur.rowcount

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

    def record_equity(self, agent_id: str, episode: int, step: int, equity: float) -> None:
        """One point of a live equity curve — read by the dashboard while a
        run is still in progress (WAL mode makes this safe concurrently)."""
        self._conn.execute(
            "INSERT INTO equity_snapshots (agent_id, episode, step, equity) VALUES (?, ?, ?, ?)",
            (agent_id, episode, step, equity),
        )
        self._conn.commit()

    def record_market(self, episode: int, step: int, closes: dict[str, float],
                      regimes: dict[str, str]) -> None:
        """The tape as the agents saw it, so a viewer can show a price
        ticker and the regime without re-running the market."""
        self._conn.executemany(
            """INSERT OR REPLACE INTO market_snapshots (episode, step, symbol, close, regime)
               VALUES (?, ?, ?, ?, ?)""",
            [(episode, step, sym, px, regimes.get(sym, "")) for sym, px in closes.items()],
        )
        self._conn.commit()

    def record_survival_event(self, day: int, agent_id: str, event: str, equity: float,
                              parent_id: str | None = None, generation: int = 0,
                              strategy: str = "", detail: str = "") -> None:
        self._conn.execute(
            """INSERT INTO survival_events (day, agent_id, event, equity, parent_id,
               generation, strategy, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (day, agent_id, event, equity, parent_id, generation, strategy, detail),
        )
        self._conn.commit()

    # ---------------------------------------------------------- sources' calls
    def record_call(self, call) -> bool:
        """Add a source's call to the ledger; False if that post already
        made this call (the same post read twice must not count twice)."""
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO source_calls (source, post_id, ts, symbol, side, text,
               url, price_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (call.source, call.post_id, call.ts, call.symbol, call.side, call.text,
             call.url, call.price_at))
        self._conn.commit()
        return cur.rowcount > 0

    def calls(self, source: str | None = None, unresolved: bool | None = None,
              limit: int = 500) -> list:
        from ..market.sources import Call
        where, args = [], []
        if source:
            where.append("source = ?"); args.append(source)
        if unresolved is True:
            where.append("resolved_ts IS NULL")
        elif unresolved is False:
            where.append("resolved_ts IS NOT NULL")
        sql = "SELECT source, post_id, ts, symbol, side, text, url, price_at, resolved_ts, " \
              "outcome, id FROM source_calls"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(limit)
        return [Call(*row) for row in self._conn.execute(sql, args).fetchall()]

    def resolve_call(self, call_id: int, resolved_ts: int, outcome: float) -> None:
        self._conn.execute("UPDATE source_calls SET resolved_ts = ?, outcome = ? WHERE id = ?",
                           (resolved_ts, outcome, call_id))
        self._conn.commit()

    def source_record(self, source: str) -> dict:
        """calls made, judged, hits (outcome > 0) and the mean outcome."""
        row = self._conn.execute(
            """SELECT COUNT(*), COUNT(resolved_ts), COALESCE(SUM(outcome > 0), 0),
               AVG(outcome) FROM source_calls WHERE source = ?""", (source,)).fetchone()
        return {"calls": row[0], "resolved": row[1], "hits": int(row[2]),
                "avg_outcome": row[3]}

    def save_state(self, key: str, value) -> None:
        """Persist a JSON-serialisable blob under `key` (live colonies keep
        their whole in-memory state here so an hourly job can resume)."""
        self._conn.execute(
            """INSERT INTO colony_state (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
               updated_at = CURRENT_TIMESTAMP""",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def load_state(self, key: str):
        row = self._conn.execute(
            "SELECT value FROM colony_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_episode_summary(self, stats, halted: bool = False) -> None:
        """Persist an EpisodeStats snapshot so the leaderboard survives the
        run and can be read by a separate dashboard process."""
        self._conn.execute(
            """INSERT INTO episode_summary (agent_id, episode, start_equity, end_equity,
               n_trades, n_wins, n_losses, n_stop_losses, fees, max_drawdown, halted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id, episode) DO UPDATE SET
                 start_equity=excluded.start_equity, end_equity=excluded.end_equity,
                 n_trades=excluded.n_trades, n_wins=excluded.n_wins,
                 n_losses=excluded.n_losses, n_stop_losses=excluded.n_stop_losses,
                 fees=excluded.fees, max_drawdown=excluded.max_drawdown,
                 halted=excluded.halted""",
            (stats.agent_id, stats.episode, stats.start_equity, stats.end_equity,
             stats.n_trades, stats.n_wins, stats.n_losses, stats.n_stop_losses,
             stats.fees, stats.max_drawdown, int(halted)),
        )
        self._conn.commit()
