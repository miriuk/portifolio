"""The survival colony on real market data, one closed candle at a time.

`run_survival` lives inside one process and a simulated market. Out in the
world a day takes a day, so the colony has to survive process restarts: an
hourly job (GitHub Actions, cron, a laptop) opens the journal, restores
every agent — wallet, positions, warmed-up indicators, parameters, streaks,
immunity — feeds it whatever candles closed since the last visit, runs the
usual end-of-day rituals when the UTC day rolls over, and saves everything
back. Trading is paper: real prices, simulated fills, no exchange account.

    colony = LiveColony.open(journal, founders, cfg, feed)
    colony.run_once()        # process every candle that closed since last time
    colony.run_forever(7)    # or stay up and tick once an hour for a week
"""
from __future__ import annotations

import inspect
import time
from collections import deque
from dataclasses import asdict, fields
from datetime import datetime, timezone

import numpy as np

from ..agents import rules
from ..agents.base import HISTORY_LEN, TradingAgent
from ..learning.memory import TradeJournal
from ..market.candle import Candle
from ..market.exchange import SimulatedExchange
from ..portfolio.risk import RiskManager
from ..portfolio.wallet import Wallet
from .episode import EpisodeResult, run_episode
from .survival import (Individual, SurvivalConfig, SurvivalResult, _end_of_day,
                       _next_id_factory, _strategy_name)

STATE_KEY = "live_colony"
AGENT_CLASSES: dict[str, type] = {
    name: cls for name, cls in inspect.getmembers(rules, inspect.isclass)
    if issubclass(cls, rules.ParamAgent) and cls is not rules.ParamAgent
}


class _OneBar:
    """A market that serves exactly the candles it was given, once."""

    def __init__(self, candles: list[Candle]):
        self._candles = candles
        self._regime: dict[str, str] = {}

    def next_candles(self) -> list[Candle]:
        return self._candles


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class LiveColony:
    def __init__(self, journal: TradeJournal, cfg: SurvivalConfig, feed,
                 founders: list[TradingAgent] | None = None,
                 warmup: int = 700, verbose: bool = True):
        self.journal = journal
        self.cfg = cfg
        self.feed = feed
        self.warmup = warmup
        self.verbose = verbose
        self.result = SurvivalResult()
        self.next_id = _next_id_factory(founders or [])
        self.rng = np.random.default_rng(cfg.seed)
        self.day = 1                 # the colony's day counter (day 1 may be a partial UTC day)
        self.hour = 0                # closed candles processed in the current day
        self.clock = 0               # continuous step counter the agents' cooldowns see
        self.last_ts: int | None = None
        self.started_at: str | None = None
        self.day_curves: dict[str, list[float]] = {}
        self.risk: dict[str, RiskManager] = {}
        self.last_prices: dict[str, float] = {}
        self.exchange = SimulatedExchange(fee_rate=getattr(cfg, "fee_rate", 0.001),
                                          seed=int(self.rng.integers(1 << 31)))
        if founders:
            for agent in founders:
                agent.starting_cash = cfg.budget
                agent.reset_wallet()
                ind = Individual(agent, _strategy_name(agent), cfg.budget, None, 0, born_day=0)
                self.result.population.append(ind)

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def open(cls, journal: TradeJournal, founders: list[TradingAgent],
             cfg: SurvivalConfig, feed, warmup: int = 700,
             verbose: bool = True) -> "LiveColony":
        """Resume the colony saved in `journal`, or found a new one."""
        saved = journal.load_state(STATE_KEY)
        if saved is not None:
            known = {f.name for f in fields(SurvivalConfig)}
            colony = cls(journal, SurvivalConfig(**{k: v for k, v in saved["config"].items()
                                                    if k in known}), feed, warmup=warmup,
                         verbose=verbose)
            if saved.get("symbol_map") and hasattr(feed, "symbols"):
                feed.symbols = dict(saved["symbol_map"])   # the colony keeps its own universe
            colony._restore(saved)
            return colony
        colony = cls(journal, cfg, feed, founders, warmup=warmup, verbose=verbose)
        for ind in colony.result.population:
            journal.record_survival_event(0, ind.agent_id, "born", cfg.budget,
                                          generation=0, strategy=ind.strategy)
        colony._warm_up()
        colony.save()
        return colony

    @property
    def alive(self) -> list[Individual]:
        return self.result.alive

    def _warm_up(self) -> None:
        """Give the founders the recent tape so their indicators work from
        the first real bar, then trade that first bar."""
        bars = self.feed.aligned(limit=self.warmup + 1)[-self.warmup:]
        if not bars:
            raise RuntimeError("the feed returned no closed candles")
        self.started_at = _utc(bars[-1][0].timestamp).isoformat()
        for candles in bars[:-1]:
            for ind in self.alive:
                ind.agent.observe(candles)
        self.last_ts = bars[-2][0].timestamp if len(bars) > 1 else None
        self.step(bars[-1])

    # ------------------------------------------------------------ ticking
    def run_once(self) -> int:
        """Process every bar that closed since the last one seen. Returns
        how many bars were processed (0 = nothing new, safe to call often)."""
        processed = 0
        for _page in range(100):                    # exchanges page their history
            bars = self.feed.aligned(limit=200, since=self.last_ts)
            if not bars:
                break
            for candles in bars:
                self.step(candles)
            processed += len(bars)
            self.save()
        if not processed and self.verbose:
            print(f"no new closed candle since "
                  f"{_utc(self.last_ts).isoformat() if self.last_ts else 'never'}")
        return processed

    def run_forever(self, days: int, sleep=time.sleep, now=time.time) -> None:
        """Stay up: tick a little after every hour boundary until `days`
        colony days have completed (or nobody is left)."""
        target_day = self.day + days
        while self.day < target_day and self.alive:
            self.run_once()
            period = self.feed.seconds
            wait = period - (now() % period) + 45      # the exchange needs a moment to close the bar
            sleep(wait)

    def step(self, candles: list[Candle]) -> None:
        """One closed bar for everyone alive; the day's rituals when the UTC
        day rolls over."""
        alive = self.alive
        if not alive:
            return
        candles = self._complete(candles)
        if self.hour == 0:
            self.day_curves = {}
            self.risk = {}                              # a fresh seatbelt every day, as in the sim
            for ind in alive:
                ind.apply_pressure(self.cfg.pressure)
        ep = run_episode(self.day, _OneBar(candles), [i.agent for i in alive], self.journal,
                         steps=1, step_offset=self.clock, record_step_offset=self.hour,
                         risk=self.risk, exchange=self.exchange)
        for agent_id, curve in ep.equity_curves.items():
            self.day_curves.setdefault(agent_id, []).extend(curve)
        self.last_prices = {c.symbol: c.close for c in candles}
        self.last_ts = candles[0].timestamp
        self.clock += 1
        self.hour += 1
        if self.verbose:
            total = sum(i.agent.wallet.equity(self.last_prices) for i in alive)
            print(f"{_utc(self.last_ts):%Y-%m-%d %H:%M} UTC  day {self.day} h{self.hour:<2} "
                  f"alive={len(alive)} colony={total:.2f}")
        if self._day_over(candles[0].timestamp):
            self._end_day(alive)

    def _complete(self, candles: list[Candle]) -> list[Candle]:
        """A pair the feed could not fetch this bar gets a flat candle at its
        last price, so positions keep their value and nobody trades on a
        hole in the tape."""
        seen = {c.symbol for c in candles}
        ts = candles[0].timestamp
        filled = list(candles)
        for symbol, price in self.last_prices.items():
            if symbol not in seen and symbol in (getattr(self.feed, "symbols", {}) or {}):
                filled.append(Candle(symbol, ts, price, price, price, price, 0.0))
        return filled

    def _day_over(self, ts: int) -> bool:
        """The bar that opened at 23:00 UTC closes the day."""
        period = self.feed.seconds
        return (ts + period) % 86400 == 0

    def _end_day(self, alive: list[Individual]) -> None:
        # the day closes on the bar's close, after this hour's trades
        ep = EpisodeResult(episode=self.day)
        for ind in alive:
            curve = list(self.day_curves.get(ind.agent_id, []))
            curve.append(ind.agent.wallet.equity(self.last_prices))
            ep.equity_curves[ind.agent_id] = curve
            peak, dd = 0.0, 0.0
            for eq in curve:
                peak = max(peak, eq)
                dd = max(dd, 1 - eq / peak if peak > 0 else 0.0)
            ep.max_drawdown[ind.agent_id] = dd
            ep.halted[ind.agent_id] = self.risk.get(ind.agent_id, RiskManager()).halted
        _end_of_day(self.day, alive, ep, self.cfg, self.rng, self.journal,
                    self.next_id, self.result, self.verbose)
        self.day += 1
        self.hour = 0
        self.day_curves = {}
        self.risk = {}

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        self.journal.save_state(STATE_KEY, {
            "config": asdict(self.cfg),
            "day": self.day, "hour": self.hour, "clock": self.clock,
            "last_ts": self.last_ts, "started_at": self.started_at,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "exchange": getattr(self.feed, "exchange_id", ""),
            "timeframe": getattr(self.feed, "timeframe", "1h"),
            "symbols": list(getattr(self.feed, "symbols", {}) or {}),
            "symbol_map": dict(getattr(self.feed, "symbols", {}) or {}),
            "tape": self._tape(),
            "counters": dict(self.next_id.counters),
            "senior": self.result.senior.agent_id if self.result.senior else None,
            "alive_per_day": self.result.alive_per_day,
            "equity_per_day": self.result.equity_per_day,
            "day_curves": self.day_curves,
            "last_prices": self.last_prices,
            "risk": {k: {"peak_equity": r.peak_equity, "halted": r.halted}
                     for k, r in self.risk.items()},
            "population": [_dump_individual(i) for i in self.result.population],
        })

    def _restore(self, saved: dict) -> None:
        self.day, self.hour, self.clock = saved["day"], saved["hour"], saved["clock"]
        self.last_ts, self.started_at = saved["last_ts"], saved.get("started_at")
        self.next_id.counters.update(saved.get("counters", {}))
        self.result.alive_per_day = list(saved.get("alive_per_day", []))
        self.result.equity_per_day = list(saved.get("equity_per_day", []))
        self.day_curves = {k: list(v) for k, v in saved.get("day_curves", {}).items()}
        self.last_prices = dict(saved.get("last_prices", {}))
        for agent_id, r in saved.get("risk", {}).items():
            rm = RiskManager()
            rm.peak_equity, rm.halted = r["peak_equity"], r["halted"]
            self.risk[agent_id] = rm
        self.result.population = [_load_individual(d) for d in saved["population"]]
        tape = saved.get("tape")
        if tape:                                    # one shared tape -> every agent's history
            for ind in self.result.population:
                ind.agent.history = {
                    sym: deque((Candle(sym, int(r[0]), *map(float, r[1:6])) for r in rows),
                               maxlen=HISTORY_LEN) for sym, rows in tape.items()}
        by_id = {i.agent_id: i for i in self.result.population}
        self.result.senior = by_id.get(saved.get("senior"))

    def _tape(self) -> dict[str, list[list[float]]]:
        """Every agent sees the same candles, so the tape is saved once: the
        longest history per symbol across the population."""
        tape: dict[str, list[list[float]]] = {}
        for ind in self.result.population:
            for sym, hist in ind.agent.history.items():
                if len(hist) > len(tape.get(sym, ())):
                    tape[sym] = [[c.timestamp, c.open, c.high, c.low, c.close, c.volume]
                                 for c in hist]
        return tape

    def status(self) -> dict:
        alive = self.alive
        equity = {i.agent_id: i.agent.wallet.equity(self.last_prices) for i in alive}
        return {
            "day": self.day, "hour": self.hour, "started_at": self.started_at,
            "last_candle": _utc(self.last_ts).isoformat() if self.last_ts else None,
            "alive": len(alive), "population": len(self.result.population),
            "interns": sum(1 for i in alive if i.generation > 0),
            "colony_equity": round(sum(equity.values()), 4),
            "invested": round(sum(equity.values()) - sum(i.agent.wallet.cash for i in alive), 4),
            "senior": self.result.senior.agent_id if self.result.senior else None,
            "prices": self.last_prices,
            "agents": [{"id": i.agent_id, "gen": i.generation, "budget": round(i.budget, 4),
                        "equity": round(equity[i.agent_id], 4), "streak": i.streak,
                        "misses": i.misses, "immune_until": i.immune_until}
                       for i in alive],
        }


# ---------------------------------------------------------------- (de)serialisation
_IND_FIELDS = [f.name for f in fields(Individual) if f.name not in ("agent",)]


def _dump_individual(ind: Individual) -> dict:
    agent = ind.agent
    return {
        **{name: getattr(ind, name) for name in _IND_FIELDS},
        "agent": {
            "cls": type(agent).__name__, "agent_id": agent.agent_id,
            "starting_cash": agent.starting_cash, "params": agent.get_params(),
            "wallet": {"cash": agent.wallet.cash, "positions": dict(agent.wallet.positions),
                       "cost_basis": dict(agent.wallet.cost_basis),
                       "fees_paid": agent.wallet.fees_paid},
            "last_trade_step": getattr(agent, "_last_trade_step", None),
            "stop_high": dict(getattr(agent, "_stop_high", {}) or {}),
        },
    }


def _load_individual(d: dict) -> Individual:
    a = d["agent"]
    cls = AGENT_CLASSES.get(a["cls"])
    if cls is None:
        raise ValueError(f"cannot restore agent class {a['cls']!r} (live colonies need "
                         f"parameter agents: {', '.join(sorted(AGENT_CLASSES))})")
    agent = cls(a["agent_id"], a["starting_cash"], params=a.get("params") or None)
    w = a["wallet"]
    agent.wallet = Wallet(cash=w["cash"], positions=dict(w.get("positions", {})),
                          cost_basis=dict(w.get("cost_basis", {})),
                          fees_paid=w.get("fees_paid", 0.0))
    agent.history = {
        sym: deque((Candle(sym, int(r[0]), *map(float, r[1:6])) for r in rows),
                   maxlen=HISTORY_LEN)
        for sym, rows in a.get("history", {}).items()}
    if a.get("last_trade_step") is not None and hasattr(agent, "_last_trade_step"):
        agent._last_trade_step = a["last_trade_step"]
    if a.get("stop_high"):
        agent._stop_high = dict(a["stop_high"])
    return Individual(agent=agent, **{name: d[name] for name in _IND_FIELDS})
