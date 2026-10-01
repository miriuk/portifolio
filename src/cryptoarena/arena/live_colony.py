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
from dataclasses import MISSING, asdict, fields
from datetime import datetime, timezone

import numpy as np

from ..agents import rules
from ..agents.base import HISTORY_LEN, TradingAgent
from ..learning.memory import TradeJournal
from ..market.candle import Candle
from ..market.exchange import SimulatedExchange
from ..market import sec
from ..market.sources import Call, Post, Source, parse_calls, signals, trust
from ..portfolio.risk import RiskManager
from ..portfolio.wallet import Wallet
from .chief import ChiefPolicy, bench_start, day_activity, report
from .desk import PMBook
from .episode import EpisodeResult, run_episode
from .survival import (Individual, SurvivalConfig, SurvivalResult, _end_of_day,
                       _next_id_factory, _strategy_name, make_desk)

STATE_KEY = "live_colony"
# The desk is the floor's policy, not the colony's history: a tick applies
# whatever the floor says today, like the list of founders.
DESK_FIELDS = ("desk_symbol_cap", "desk_gross_cap", "pm", "pm_consensus", "pm_band")
AGENT_CLASSES: dict[str, type] = {
    name: cls for name, cls in inspect.getmembers(rules, inspect.isclass)
    if issubclass(cls, rules.ParamAgent) and cls is not rules.ParamAgent
}


class _OneBar:
    """A market that serves exactly the candles it was given, once."""

    def __init__(self, candles: list[Candle], sentiment: int | None = None,
                 signals: dict[str, float] | None = None):
        self._candles = candles
        self._regime: dict[str, str] = {}
        self._sentiment = sentiment
        self._signals = signals or {}

    def next_candles(self) -> list[Candle]:
        return self._candles

    def sentiment_at(self, ts: int) -> int | None:
        return self._sentiment

    def signals_at(self, ts: int) -> dict[str, float]:
        return self._signals


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
        self.min_costs: dict[str, float] = {}   # the exchange's smallest order per symbol (quote)
        self.sentiment: int | None = None       # the latest Crypto Fear & Greed reading
        self.sources: list[Source] = []         # the accounts the colony listens to
        self.source_cursor: dict[str, dict] = {}  # per handle: last post id seen, user id
        self.exchange = SimulatedExchange(fee_rate=getattr(cfg, "fee_rate", 0.001),
                                          seed=int(self.rng.integers(1 << 31)))
        self.desk = None                        # the roles above the agents (arena/desk.py)
        self.chief: ChiefPolicy | None = None   # who reads it all and calls the owner (arena/chief.py)
        self.bench_start: dict | None = None    # the benchmark at the founding: the line to beat
        self.pm_start: dict | None = None       # when the PM's book opened, and the colony then
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
             verbose: bool = True, sources: list[Source] | None = None,
             chief: ChiefPolicy | None = None) -> "LiveColony":
        """Resume the colony saved in `journal`, or found a new one."""
        saved = journal.load_state(STATE_KEY)
        if saved is not None:
            known = {f.name for f in fields(SurvivalConfig)}
            colony = cls(journal, SurvivalConfig(**{k: v for k, v in saved["config"].items()
                                                    if k in known}), feed, warmup=warmup,
                         verbose=verbose)
            if saved.get("symbol_map") and hasattr(feed, "symbols"):
                feed.symbols = dict(saved["symbol_map"])   # the colony keeps its own universe
            colony.sources = list(sources or [])
            colony.chief = chief
            colony._restore(saved)
            if founders:                          # a real tick: the floor's desk policy applies
                for name in DESK_FIELDS:
                    setattr(colony.cfg, name, getattr(cfg, name))
            colony._hire(founders)
            colony._retire(founders)
            colony._staff_desk(saved.get("desk"))
            return colony
        colony = cls(journal, cfg, feed, founders, warmup=warmup, verbose=verbose)
        colony.sources = list(sources or [])
        colony.chief = chief
        for ind in colony.result.population:
            journal.record_survival_event(0, ind.agent_id, "born", cfg.budget,
                                          generation=0, strategy=ind.strategy)
        colony._staff_desk(None)
        colony._warm_up()
        colony.save()
        return colony

    @property
    def alive(self) -> list[Individual]:
        return self.result.alive

    def _staff_desk(self, saved: dict | None) -> None:
        """The desk the configuration asks for, with the counters and the
        PM's book carried over from the saved state. A PM added to a
        running colony opens its book today, with the founders' capital,
        and is compared with the colony from that day on."""
        founding = sum(i.budget for i in self.result.population if i.generation == 0)
        self.desk = make_desk(self.cfg, self.journal, capital=founding)
        saved = saved or {}
        self.pm_start = saved.get("pm_start")
        if self.desk is None:
            return
        self.desk.vetoes = saved.get("vetoes", 0)
        self.desk.clipped = saved.get("clipped", 0)
        if self.desk.pm is not None:
            if saved.get("pm"):
                book = PMBook.load(saved["pm"])
                book.consensus, book.band = self.cfg.pm_consensus, self.cfg.pm_band
                book.exchange = self.desk.pm.exchange
                self.desk.pm = book
            else:
                colony = (sum(i.agent.wallet.equity(self.last_prices) for i in self.alive)
                          if self.last_prices else founding)
                self.pm_start = {"day": self.day, "ts": self.last_ts, "colony": round(colony, 4)}
                self.journal.record_survival_event(
                    self.day, "pm", "pm_opened", founding,
                    detail=f"desk: the PM opens its book with {founding:.2f}")
                self.save()

    def _retire(self, founders: list[TradingAgent]) -> None:
        """A specialist dropped from the floor leaves the running colony:
        retired today, positions closed at the last prices, budget gone
        with them, like a dismissal without the blame. The floor's list of
        founders is the source of truth; interns are never retired here."""
        if not founders:
            return                                   # a bare resume (status, dashboard) changes nothing
        keep = {a.agent_id for a in founders}
        retired = False
        for ind in self.alive:
            if ind.generation > 0 or ind.agent_id in keep:
                continue
            equity = ind.agent.wallet.equity(self.last_prices)
            ind.died_day = self.day
            self.journal.record_survival_event(self.day, ind.agent_id, "retired", equity,
                                               ind.parent_id, ind.generation, ind.strategy,
                                               detail="dropped from the floor")
            if self.verbose:
                print(f"retired {ind.agent_id} ({ind.strategy}) on day {self.day} at {equity:.2f}")
            retired = True
        if retired:
            self.save()

    def _hire(self, founders: list[TradingAgent]) -> None:
        """A specialist added to the floor after the founding joins the
        running colony: a fresh budget, the shared tape as history, born
        today. The colony keeps its history instead of being re-founded."""
        known = {i.agent_id for i in self.result.population}
        tape = self._tape()
        hired = False
        for agent in founders or []:
            if agent.agent_id in known:
                continue
            agent.starting_cash = self.cfg.budget
            agent.reset_wallet()
            agent.history = {
                sym: deque((Candle(sym, int(r[0]), *map(float, r[1:6])) for r in rows),
                           maxlen=HISTORY_LEN) for sym, rows in tape.items()}
            ind = Individual(agent, _strategy_name(agent), self.cfg.budget, None, 0,
                             born_day=self.day)
            self.result.population.append(ind)
            self.journal.record_survival_event(self.day, agent.agent_id, "born",
                                               self.cfg.budget, generation=0,
                                               strategy=ind.strategy, detail="hired")
            if self.verbose:
                print(f"hired {agent.agent_id} ({ind.strategy}) on day {self.day}")
            hired = True
        if hired:
            self.save()

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
        if hasattr(self.feed, "sentiment"):
            fresh = self.feed.sentiment()
            if fresh is not None:
                self.sentiment = int(fresh)
        self._read_sources()
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
        if self.desk is not None:
            self.desk.day = self.day
        ep = run_episode(self.day, _OneBar(candles, self.sentiment, self.signals()),
                         [i.agent for i in alive],
                         self.journal,
                         steps=1, step_offset=self.clock, record_step_offset=self.hour,
                         risk=self.risk, exchange=self.exchange, desk=self.desk)
        for agent_id, curve in ep.equity_curves.items():
            self.day_curves.setdefault(agent_id, []).extend(curve)
        self.last_prices = {c.symbol: c.close for c in candles}
        self.last_ts = candles[0].timestamp
        self.clock += 1
        self.hour += 1
        self._judge_calls()
        if self.verbose:
            total = sum(i.agent.wallet.equity(self.last_prices) for i in alive)
            print(f"{_utc(self.last_ts):%Y-%m-%d %H:%M} UTC  day {self.day} h{self.hour:<2} "
                  f"alive={len(alive)} colony={total:.2f}")
        if self._day_over(candles[0].timestamp):
            self._end_day(alive)

    # ------------------------------------------------------------ sources
    def _read_sources(self) -> int:
        """Ask each source for what is new and file its calls: X accounts
        through the feed (the X API, when a token is configured), SEC
        Form 4 insider purchases from EDGAR. Posts by hand come in through
        `ingest` directly."""
        filed = 0
        for src in self.sources:
            cur = self.source_cursor.setdefault(src.handle, {})
            try:
                if src.handle == sec.SOURCE:
                    if sec.user_agent() is None:
                        print(f"[sources] {src.handle}: quiet until the repository secret "
                              "SEC_USER_AGENT ('Name e-mail') is set")
                        continue
                    symbols = list(self.last_prices) or list(getattr(self.feed, "symbols", {}) or {})
                    calls, cur["since"] = sec.fetch_calls(symbols, since=cur.get("since"))
                    filed += self.file_calls(calls)
                    continue
                if not hasattr(self.feed, "posts"):
                    continue
                user_id, posts = self.feed.posts(src.handle, since_id=cur.get("since_id"),
                                                 user_id=cur.get("user_id"))
            except Exception as exc:     # noqa: BLE001 — a source down never stops the tick
                print(f"[sources] {src.handle}: {exc}")
                continue
            if user_id:
                cur["user_id"] = user_id
            if posts:
                cur["since_id"] = max(posts, key=lambda p: int(p.post_id)).post_id
                filed += self.ingest(posts)
        return filed

    def _source(self, handle: str) -> Source:
        for src in self.sources:
            if src.handle == handle:
                return src
        return Source(handle)                       # a hand-fed source nobody registered

    def ingest(self, posts: list[Post]) -> int:
        """File the calls the posts make. Returns how many new calls went
        into the ledger."""
        symbols = list(self.last_prices) or list(getattr(self.feed, "symbols", {}) or {})
        return self.file_calls([call for post in posts for call in parse_calls(post, symbols)])

    def file_calls(self, calls: list[Call]) -> int:
        """File calls at the price the colony sees for them (the bar of the
        call if it is on the tape, else the last price). Returns how many
        were new to the ledger."""
        tape = self._tape()
        filed = 0
        for call in calls:
            call.price_at = self._price_at(call.symbol, call.ts, tape)
            if call.price_at is None:
                continue
            if self.journal.record_call(call):
                filed += 1
                if self.verbose:
                    print(f"call {call.source}: {call.symbol} "
                          f"{'long' if call.side > 0 else 'short'} at {call.price_at:.4g}")
        if filed:
            self.save()
        return filed

    def _price_at(self, symbol: str, ts: int, tape: dict) -> float | None:
        rows = tape.get(symbol) or []
        for r in rows:
            if r[0] >= ts:                          # the first bar closed after the post
                return float(r[4])
        return self.last_prices.get(symbol)

    def _judge_calls(self) -> None:
        """A call whose horizon has passed is judged at the last price:
        outcome = the return in the call's direction. The source's trust
        is nothing but the record of these."""
        if self.last_ts is None:
            return
        for call in self.journal.calls(unresolved=True):
            horizon = self._source(call.source).horizon_days * 86400
            price = self.last_prices.get(call.symbol)
            if call.ts + horizon > self.last_ts or not price or not call.price_at:
                continue
            outcome = call.side * (price / call.price_at - 1)
            self.journal.resolve_call(call.id, self.last_ts, outcome)
            if self.verbose:
                print(f"judged @{call.source} {call.symbol} "
                      f"{'long' if call.side > 0 else 'short'}: {outcome:+.2%}")

    def trust(self, handle: str) -> float:
        rec = self.journal.source_record(handle)
        return round(trust(self._source(handle), rec["resolved"], rec["hits"]), 4)

    def signals(self) -> dict[str, float]:
        """What the sources say right now, per symbol: their open calls
        weighted by trust, in [-1, 1]."""
        active = self.journal.calls(unresolved=True)
        if not active:
            return {}
        weights = {h: self.trust(h) for h in {c.source for c in active}}
        return signals(active, weights)

    def sources_summary(self) -> list[dict]:
        handles = [s.handle for s in self.sources]
        for c in self.journal.calls(limit=1000):
            if c.source not in handles:
                handles.append(c.source)
        out = []
        for h in handles:
            src, rec = self._source(h), self.journal.source_record(h)
            out.append({
                "handle": h, "label": src.label or h, "url": src.link,
                "trust": self.trust(h), "prior": src.prior, "horizon_days": src.horizon_days,
                "calls": rec["calls"], "resolved": rec["resolved"], "hits": rec["hits"],
                "hit_rate": round(rec["hits"] / rec["resolved"], 3) if rec["resolved"] else None,
                "avg_outcome": round(rec["avg_outcome"], 4) if rec["avg_outcome"] is not None
                else None,
                "active": [{"symbol": c.symbol, "side": "long" if c.side > 0 else "short",
                            "ts": c.ts, "price_at": c.price_at, "url": c.url, "text": c.text}
                           for c in self.journal.calls(source=h, unresolved=True, limit=20)],
            })
        return out

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
        ep = EpisodeResult(episode=self.day, last_prices=dict(self.last_prices))
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
        if self.desk is not None and self.desk.pm is not None:
            self.desk.pm.end_day(self.last_prices)
        self.day += 1
        self.hour = 0
        self.day_curves = {}
        self.risk = {}
        note = self.chief_note()
        if note is not None:                     # the day's note goes on the desk feed
            self.journal.record_survival_event(
                note["day"], "chief", "chief_note", round(note["colony_return"] or 0.0, 6),
                detail=" ".join(note["lines"]) + (" Decidir: " + "; ".join(
                    d["title"] for d in note["decisions"]) if note["decisions"] else ""))

    def chief_note(self, status: dict | None = None, now: float | None = None) -> dict | None:
        """The chief of staff's note on the last closed day, and the
        decisions it raises (arena/chief.py); None without a chief."""
        if self.chief is None:
            return None
        if self.bench_start is None or self.bench_start.get("symbol") != self.chief.benchmark:
            self.bench_start = bench_start(self._tape(), self.chief.benchmark, self.started_at)
        status = status or self.status(chief=False)
        founding = sum(i.budget for i in self.result.population if i.generation == 0)
        day = max(self.day - (1 if self.hour == 0 else 0), 0)
        return report(status, day_activity(self.journal, day), self.bench_start, founding,
                      self.chief, now=now)

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
            "min_costs": self.min_costs,
            "sentiment": self.sentiment,
            "source_cursor": self.source_cursor,
            "sources": self.sources_summary(),
            "signals": self.signals(),
            "risk": {k: {"peak_equity": r.peak_equity, "halted": r.halted}
                     for k, r in self.risk.items()},
            "population": [_dump_individual(i) for i in self.result.population],
            "desk": self._desk_state(),
            "bench_start": self.bench_start,
        })

    def _desk_state(self) -> dict | None:
        if self.desk is None:
            return {"pm_start": self.pm_start} if self.pm_start else None
        return {"vetoes": self.desk.vetoes, "clipped": self.desk.clipped,
                "pm": self.desk.pm.dump() if self.desk.pm is not None else None,
                "pm_start": self.pm_start}

    def desk_status(self) -> dict | None:
        """What the desk did: the risk officer's refusals and the PM's book
        next to the colony over the same days."""
        if self.desk is None:
            return None
        out = {"symbol_cap": self.cfg.desk_symbol_cap, "gross_cap": self.cfg.desk_gross_cap,
               "vetoes": self.desk.vetoes, "clipped": self.desk.clipped}
        prices = self.last_prices
        alive = self.alive
        colony = sum(i.agent.wallet.equity(prices) for i in alive)
        if colony > 0 and prices:
            per: dict[str, float] = {}
            for i in alive:
                for sym, q in i.agent.wallet.positions.items():
                    per[sym] = per.get(sym, 0.0) + abs(q) * prices.get(sym, 0.0)
            out["exposure"] = {sym: round(v / colony, 4) for sym, v in
                               sorted(per.items(), key=lambda kv: -kv[1])}
            out["holders"] = {sym: sum(1 for i in alive if i.agent.wallet.positions.get(sym))
                              for sym in per}
        pm = self.desk.pm
        if pm is not None:
            eq = pm.wallet.equity(prices)
            start = self.pm_start or {}
            base = start.get("colony")
            out["pm"] = {
                "since_day": start.get("day", 0),
                "capital": round(pm.capital, 4), "equity": round(eq, 4),
                "return": round(eq / pm.capital - 1, 6) if pm.capital else None,
                "colony_return": round(colony / base - 1, 6) if base else None,
                "consensus": pm.consensus, "band": pm.band,
                "fees": round(pm.wallet.fees_paid, 4),
                "weights": {sym: round(q * prices.get(sym, 0.0) / eq, 4)
                            for sym, q in pm.wallet.positions.items()} if eq > 0 else {},
                "targets": {k: round(v, 4) for k, v in pm.targets.items()},
                "fills": pm.fills[-10:],
            }
        return out

    def _restore(self, saved: dict) -> None:
        self.day, self.hour, self.clock = saved["day"], saved["hour"], saved["clock"]
        self.last_ts, self.started_at = saved["last_ts"], saved.get("started_at")
        self.next_id.counters.update(saved.get("counters", {}))
        self.result.alive_per_day = list(saved.get("alive_per_day", []))
        self.result.equity_per_day = list(saved.get("equity_per_day", []))
        self.day_curves = {k: list(v) for k, v in saved.get("day_curves", {}).items()}
        self.last_prices = dict(saved.get("last_prices", {}))
        self.bench_start = saved.get("bench_start")
        self.min_costs = dict(saved.get("min_costs", {}))
        self.sentiment = saved.get("sentiment")
        self.source_cursor = {k: dict(v) for k, v in (saved.get("source_cursor") or {}).items()}
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

    def readiness(self, last: int = 200) -> dict:
        """Real-money readiness: how many of the colony's recent buys were
        big enough for the exchange to accept (its minimum order per
        symbol), and the budget per agent that would make the typical
        order clear that line."""
        if not self.min_costs:
            return {}
        rows = self.journal._conn.execute(
            "SELECT symbol, quantity * price FROM trades WHERE side = 'buy' "
            "ORDER BY id DESC LIMIT ?", (last,)).fetchall()
        sized = [(sym, value) for sym, value in rows if sym in self.min_costs]
        if not sized:
            return {"orders": 0, "executable": None, "min_costs": self.min_costs}
        ok = sum(1 for sym, value in sized if value >= self.min_costs[sym])
        ratios = sorted(self.min_costs[sym] / value for sym, value in sized if value > 0)
        typical = ratios[len(ratios) // 2] if ratios else 1.0        # the median order
        worst = ratios[-1] if ratios else 1.0                         # the smallest top-up
        return {"orders": len(sized), "executable": round(ok / len(sized), 3),
                "budget_for_typical": round(self.cfg.budget * max(typical, 1.0), 2),
                "budget_for_all": round(self.cfg.budget * max(worst, 1.0), 2),
                "min_costs": self.min_costs}

    def status(self, chief: bool = True) -> dict:
        alive = self.alive
        equity = {i.agent_id: i.agent.wallet.equity(self.last_prices) for i in alive}
        out = {
            "day": self.day, "hour": self.hour, "started_at": self.started_at,
            "last_candle": _utc(self.last_ts).isoformat() if self.last_ts else None,
            "alive": len(alive), "population": len(self.result.population),
            "interns": sum(1 for i in alive if i.generation > 0),
            "colony_equity": round(sum(equity.values()), 4),
            "invested": round(sum(abs(q) * self.last_prices.get(sym, 0.0)
                                  for i in alive for sym, q in i.agent.wallet.positions.items()), 4),
            "senior": self.result.senior.agent_id if self.result.senior else None,
            "prices": self.last_prices,
            "sentiment": self.sentiment,
            "signals": self.signals(),
            "sources": self.sources_summary(),
            "readiness": self.readiness(),
            "desk": self.desk_status(),
            "agents": [{"id": i.agent_id, "gen": i.generation, "budget": round(i.budget, 4),
                        "equity": round(equity[i.agent_id], 4), "streak": i.streak,
                        "misses": i.misses, "immune_until": i.immune_until}
                       for i in alive],
        }
        if chief and self.chief is not None:
            out["chief"] = self.chief_note(status=out)
        return out


# ---------------------------------------------------------------- (de)serialisation
_IND_FIELDS = [f.name for f in fields(Individual) if f.name not in ("agent",)]
# Fields added after a colony was founded are absent from its saved state:
# restore them at their dataclass default instead of crashing the next tick.
_IND_DEFAULTS = {f.name: (f.default if f.default is not MISSING else
                          f.default_factory() if f.default_factory is not MISSING else None)
                 for f in fields(Individual) if f.name != "agent"}


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
            "hold_symbols": list(getattr(agent, "hold_symbols", []) or []),
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
                          fees_paid=w.get("fees_paid", 0.0), allow_short=agent.allow_short)
    agent.history = {
        sym: deque((Candle(sym, int(r[0]), *map(float, r[1:6])) for r in rows),
                   maxlen=HISTORY_LEN)
        for sym, rows in a.get("history", {}).items()}
    if a.get("last_trade_step") is not None and hasattr(agent, "_last_trade_step"):
        agent._last_trade_step = a["last_trade_step"]
    if a.get("stop_high"):
        agent._stop_high = dict(a["stop_high"])
    if a.get("hold_symbols") and hasattr(agent, "hold_symbols"):
        agent.hold_symbols = list(a["hold_symbols"])
    return Individual(agent=agent, **{name: d.get(name, _IND_DEFAULTS[name]) for name in _IND_FIELDS})
