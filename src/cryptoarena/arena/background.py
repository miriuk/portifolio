"""Run a tournament on a background thread so a web UI can start it and
keep rendering while it writes to the journal.

Streamlit re-executes the page script on every interaction, so the run's
state lives at module level (one process, one run at a time) rather than
in any per-page object.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field

from ..learning.memory import TradeJournal
from .tournament import run_tournament


@dataclass
class RunConfig:
    db_path: str = "arena.db"
    episodes: int = 3
    steps: int = 24 * 30
    cash: float = 10_000.0
    seed: int | None = None
    endogenous: bool = False
    llm: bool = False
    llm_model: str = "claude-opus-5"
    debate: bool = False


@dataclass
class RunState:
    config: RunConfig
    thread: threading.Thread
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None

    @property
    def running(self) -> bool:
        return self.thread.is_alive()


_lock = threading.Lock()
_current: RunState | None = None


def current_run() -> RunState | None:
    return _current


def start_tournament(config: RunConfig) -> RunState:
    """Launch a tournament in a daemon thread; raises if one is already running."""
    global _current
    with _lock:
        if _current is not None and _current.running:
            raise RuntimeError("a tournament is already running")

        def worker() -> None:
            # the journal must be created in the thread that uses it (sqlite)
            journal = TradeJournal(config.db_path)
            try:
                from ..cli import build_agents
                agents = build_agents(config.cash, config.llm, config.llm_model,
                                      journal=journal, debate=config.debate)
                run_tournament(agents, journal, episodes=config.episodes,
                               steps_per_episode=config.steps, seed=config.seed,
                               endogenous=config.endogenous, verbose=False)
            except Exception:
                state.error = traceback.format_exc()
            finally:
                journal.close()
                state.finished_at = time.time()

        thread = threading.Thread(target=worker, name="cryptoarena-run", daemon=True)
        state = RunState(config=config, thread=thread)
        _current = state
        thread.start()
        return state
