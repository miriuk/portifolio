"""Survival mode: every agent gets a budget and a daily target.

End a day above the target and you may clone yourself (the child is paid
out of your own surplus, with mutated parameters and your lessons). End a
day below the death line — or trip the intraday kill switch — and you are
switched off for good. Memory persists; wallets do NOT reset between days.

This is the "daily quota or die" scheme from the viral self-replicating
agent experiments, made honest: clones cost real (simulated) money, so the
colony only grows when someone actually made some, and every death is
recorded so survivorship bias can't hide the losers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..agents.base import TradingAgent
from ..learning.memory import TradeJournal
from ..learning.reflection import compute_stats, reflect_on_episode
from ..market.endogenous import EndogenousMarket
from ..market.synthetic import SyntheticMarket
from .episode import run_episode


@dataclass
class SurvivalConfig:
    days: int = 30
    steps_per_day: int = 24
    budget: float = 1_000.0
    daily_target: float = 0.005     # +0.5% on the day's opening equity
    death_below: float = 0.6        # dead when equity < own budget * this
    daily_cost: float = 0.001       # cost of living (compute/API), fraction of own budget per day
    max_population: int = 12
    min_clone_budget: float = 0.05  # a child needs at least this * budget to be born
    pressure: float = 0.0           # each missed target scales order size by (1 + pressure)
    seed: int | None = None
    endogenous: bool = True
    symbols: dict[str, float] | None = None


@dataclass
class Individual:
    agent: TradingAgent
    strategy: str
    budget: float
    parent_id: str | None
    generation: int
    born_day: int
    died_day: int | None = None
    streak: int = 0
    misses: int = 0
    base_order_frac: float | None = None

    def apply_pressure(self, pressure: float) -> None:
        """The quota-or-die incentive: after a miss, bet bigger tomorrow."""
        params = self.agent.get_params()
        if not pressure or params is None or "order_frac" not in params:
            return
        if self.base_order_frac is None:
            self.base_order_frac = params["order_frac"]
        scaled = min(self.base_order_frac * (1 + pressure) ** self.misses, 0.30)
        self.agent.set_params({**params, "order_frac": scaled})

    @property
    def agent_id(self) -> str:
        return self.agent.agent_id

    @property
    def alive(self) -> bool:
        return self.died_day is None


@dataclass
class SurvivalResult:
    population: list[Individual] = field(default_factory=list)
    alive_per_day: list[int] = field(default_factory=list)
    equity_per_day: list[float] = field(default_factory=list)

    @property
    def alive(self) -> list[Individual]:
        return [i for i in self.population if i.alive]


def _strategy_name(agent: TradingAgent) -> str:
    return type(agent).__name__.removesuffix("Agent").lower()


def run_survival(
    founders: list[TradingAgent],
    journal: TradeJournal,
    config: SurvivalConfig | None = None,
    verbose: bool = True,
) -> SurvivalResult:
    cfg = config or SurvivalConfig()
    rng = np.random.default_rng(cfg.seed)
    symbols = cfg.symbols or {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 150.0}
    market_cls = EndogenousMarket if cfg.endogenous else SyntheticMarket
    market = market_cls(symbols, seed=int(rng.integers(1 << 31)))  # one continuous market

    result = SurvivalResult()
    counters: dict[str, int] = {}

    def next_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    for agent in founders:
        prefix = agent.agent_id.rsplit("-", 1)[0]
        n = agent.agent_id.rsplit("-", 1)[-1]
        if n.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(n))
        agent.starting_cash = cfg.budget
        agent.reset_wallet()
        ind = Individual(agent, _strategy_name(agent), cfg.budget, None, 0, born_day=0)
        result.population.append(ind)
        journal.record_survival_event(0, ind.agent_id, "born", cfg.budget,
                                      generation=0, strategy=ind.strategy)

    for day in range(1, cfg.days + 1):
        alive = result.alive
        if not alive:
            break
        for ind in alive:
            ind.apply_pressure(cfg.pressure)
        # history is NOT cleared: the market is continuous, indicators stay warm
        ep = run_episode(day, market, [i.agent for i in alive], journal,
                         steps=cfg.steps_per_day, verbose=False)

        births: list[Individual] = []
        deaths: list[str] = []
        for ind in alive:
            curve = ep.equity_curves[ind.agent_id]
            cost = ind.budget * cfg.daily_cost
            ind.agent.wallet.cash -= cost           # rent is due whether you traded or not
            start, end = curve[0], curve[-1] - cost
            stats = compute_stats(ind.agent_id, day, journal.trades_for(ind.agent_id, day),
                                  start_equity=start, end_equity=end,
                                  max_drawdown=ep.max_drawdown[ind.agent_id])
            journal.record_episode_summary(stats, halted=ep.halted[ind.agent_id])
            ind.agent.learn(reflect_on_episode(journal, stats))

            if ep.halted[ind.agent_id] or end < ind.budget * cfg.death_below:
                ind.died_day = day
                deaths.append(ind.agent_id)
                journal.record_survival_event(
                    day, ind.agent_id, "died", end, ind.parent_id, ind.generation,
                    ind.strategy, "kill switch" if ep.halted[ind.agent_id]
                    else f"below {cfg.death_below:.0%} of budget")
                continue

            if end >= start * (1 + cfg.daily_target):
                ind.streak += 1
                ind.misses = 0
                journal.record_survival_event(
                    day, ind.agent_id, "target_hit", end, ind.parent_id, ind.generation,
                    ind.strategy, f"streak {ind.streak}")
                child = _try_clone(ind, day, end, cfg, rng, journal, next_id,
                                   population_size=len(alive) + len(births))
                if child is not None:
                    births.append(child)
            else:
                ind.streak = 0
                ind.misses += 1
            journal.record_survival_event(day, ind.agent_id, "survived", end,
                                          ind.parent_id, ind.generation, ind.strategy,
                                          f"cost {cost:.2f}")
            journal.decay_lessons(ind.agent_id)

        result.population.extend(births)
        survivors = result.alive
        result.alive_per_day.append(len(survivors))
        total = sum(ep.equity_curves[i.agent_id][-1] - i.budget * cfg.daily_cost
                    for i in survivors if i.agent_id in ep.equity_curves) \
            + sum(i.budget for i in births)
        result.equity_per_day.append(total)
        if verbose:
            print(f"day {day:>3}: alive={len(survivors):<3} born={len(births)} "
                  f"died={len(deaths)} colony={total:,.0f}"
                  + (f"  +{', '.join(b.agent_id for b in births)}" if births else "")
                  + (f"  -{', '.join(deaths)}" if deaths else ""))
    return result


def _try_clone(parent: Individual, day: int, equity: float, cfg: SurvivalConfig, rng,
               journal, next_id, population_size: int) -> Individual | None:
    """A child is paid out of the parent's profit (equity above its own
    budget), in cash — so a parent fully invested has to wait."""
    if population_size >= cfg.max_population:
        return None
    wallet = parent.agent.wallet
    profit = equity - parent.budget
    child_budget = min(parent.budget, profit, wallet.cash)
    if child_budget < parent.budget * cfg.min_clone_budget:
        return None
    child_id = next_id(parent.agent_id.rsplit("-", 1)[0])
    child_agent = parent.agent.clone(child_id, child_budget, rng)
    if child_agent is None:
        return None
    wallet.cash -= child_budget
    child = Individual(child_agent, parent.strategy, child_budget, parent.agent_id,
                       parent.generation + 1, born_day=day)
    inherited = journal.lessons_for(parent.agent_id)
    child_agent.learn(inherited)
    for lesson in inherited:
        journal.add_lesson(child_id, day, lesson)
    journal.add_lesson(child_id, day,
                       f"day {day}: born from {parent.agent_id} (generation "
                       f"{child.generation}) with {child_budget:.0f} — inherited its lessons.")
    params = child_agent.get_params()
    if params is not None:
        journal.save_params(child_id, params, child.generation)
    journal.record_survival_event(day, parent.agent_id, "cloned", wallet.cash,
                                  parent.parent_id, parent.generation, parent.strategy,
                                  f"child {child_id} with {child_budget:.0f}")
    journal.record_survival_event(day, child_id, "born", child_budget, parent.agent_id,
                                  child.generation, child.strategy)
    return child
