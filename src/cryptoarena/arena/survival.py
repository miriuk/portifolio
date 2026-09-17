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
    budget: float = 5.0             # a fiver per agent (quote units)
    daily_target: float = 0.005     # +0.5% on the day's opening equity
    death_below: float = 0.6        # dead when equity < own budget * this
    daily_cost: float = 0.001       # cost of living (compute/API), fraction of own budget per day
    max_population: int = 12
    clone_at: float = 2.0           # hire a clone only once equity reaches this × own budget
    pressure: float = 0.0           # each missed target scales order size by (1 + pressure)
    week_days: int = 7              # happy hour every N days for whoever beat the weekly target
    explore_every: int = 3          # every Nth intern is born mutated (exploration); the rest are faithful copies
    imitation_rate: float = 0.5     # weekly: interns move this far towards the best specialist's params
    tip_rate: float = 0.1           # a tip also nudges the intern's params towards the mentor's
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
    week_start_equity: float | None = None
    immune_until: int = 0          # last week's winners cannot be let go until this day

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
                         steps=cfg.steps_per_day, verbose=False,
                         step_offset=(day - 1) * cfg.steps_per_day)

        births: list[Individual] = []
        deaths: list[str] = []
        for ind in alive:
            curve = ep.equity_curves[ind.agent_id]
            cost = ind.budget * cfg.daily_cost
            ind.agent.wallet.cash -= cost           # rent is due whether you traded or not
            start, end = curve[0], curve[-1] - cost
            if ind.week_start_equity is None:
                ind.week_start_equity = start
            stats = compute_stats(ind.agent_id, day, journal.trades_for(ind.agent_id, day),
                                  start_equity=start, end_equity=end,
                                  max_drawdown=ep.max_drawdown[ind.agent_id])
            journal.record_episode_summary(stats, halted=ep.halted[ind.agent_id])
            ind.agent.learn(reflect_on_episode(journal, stats))

            verdict = _let_go(ind, end, ep.halted[ind.agent_id], cfg, day)
            if verdict == "spared":
                journal.record_survival_event(
                    day, ind.agent_id, "spared", end, ind.parent_id, ind.generation,
                    ind.strategy, f"immunity until day {ind.immune_until}")
            elif verdict:
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
            else:
                ind.streak = 0
                ind.misses += 1
                _consult_mentor(ind, day, alive, journal, cfg.tip_rate)
            # hiring is about the money, not the day: double your budget, hire a clone
            n_interns = sum(1 for i in result.population if i.generation > 0) + len(births)
            child = _try_clone(ind, day, end, cfg, rng, journal, next_id,
                               population_size=len(alive) + len(births),
                               mutate=(n_interns + 1) % cfg.explore_every == 0)
            if child is not None:
                births.append(child)
            journal.record_survival_event(day, ind.agent_id, "survived", end,
                                          ind.parent_id, ind.generation, ind.strategy,
                                          f"cost {cost:.2f}")
            journal.decay_lessons(ind.agent_id)

        if day % cfg.week_days == 0:
            still_here = [i for i in alive if i.alive]
            _happy_hour(day, day // cfg.week_days, still_here, cfg, journal)
            _weekly_training(day, still_here, cfg, journal)
        result.population.extend(births)
        survivors = result.alive
        for ind in survivors:
            params = ind.agent.get_params()
            if params is not None:
                prev = journal.load_params(ind.agent_id)
                journal.save_params(ind.agent_id, params, prev[1] if prev else ind.generation)
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


def _let_go(ind: Individual, end_equity: float, halted: bool, cfg: SurvivalConfig,
            day: int = 0) -> str | bool:
    """Only interns can be dismissed; specialists stay, whatever their
    numbers, because their lessons are what the interns learn from.
    Last week's winners are immune: returns "spared" instead of True."""
    if ind.generation == 0:
        return False
    if not (halted or end_equity < ind.budget * cfg.death_below):
        return False
    return "spared" if ind.immune_until and day <= ind.immune_until else True


def _happy_hour(day: int, week: int, alive: list[Individual], cfg: SurvivalConfig,
                journal: TradeJournal) -> list[str]:
    """End of week: whoever beat the weekly target gets a party (praise,
    motivation); the best of them is employee of the week (ego). Returns
    the winners' ids, best first."""
    weekly_target = (1 + cfg.daily_target) ** cfg.week_days - 1
    scored = []
    for ind in alive:
        if not ind.week_start_equity:
            continue
        # equity now, net of this day's rent, as the day's own summary saw it
        end = journal._conn.execute(
            "SELECT end_equity FROM episode_summary WHERE agent_id = ? AND episode = ?",
            (ind.agent_id, day)).fetchone()
        if end is None:
            continue
        ret = end[0] / ind.week_start_equity - 1
        scored.append((ret, ind))
        ind.week_start_equity = None   # next week starts tomorrow
    winners = sorted([(r, i) for r, i in scored if r >= weekly_target],
                     key=lambda ri: ri[0], reverse=True)
    for ret, ind in winners:
        journal.record_survival_event(day, ind.agent_id, "party", ret, ind.parent_id,
                                      ind.generation, ind.strategy, f"week {week}: {ret:+.1%}")
        # the prize that matters: a week during which missing the target cannot get you fired
        ind.immune_until = day + cfg.week_days
        journal.record_survival_event(day, ind.agent_id, "immune", ret, ind.parent_id,
                                      ind.generation, ind.strategy,
                                      f"until day {ind.immune_until}")
    if winners:
        ret, best = winners[0]
        journal.record_survival_event(day, best.agent_id, "employee_of_week", ret,
                                      best.parent_id, best.generation, best.strategy,
                                      f"week {week}: {ret:+.1%}")
        journal.add_lesson(best.agent_id, day,
                           f"day {day}: employee of the week {week} with {ret:+.1%} — "
                           "lean into this setup.")
    return [i.agent_id for _, i in winners]


def _week_return(journal: TradeJournal, agent_id: str, day: int, week_days: int) -> float | None:
    rows = journal._conn.execute(
        """SELECT start_equity, end_equity FROM episode_summary
           WHERE agent_id = ? AND episode > ? AND episode <= ? ORDER BY episode""",
        (agent_id, day - week_days, day)).fetchall()
    if not rows or rows[0][0] <= 0:
        return None
    return rows[-1][1] / rows[0][0] - 1


def _weekly_training(day: int, alive: list[Individual], cfg: SurvivalConfig,
                     journal: TradeJournal) -> list[tuple[str, str]]:
    """Imitation learning: every intern moves its parameters part of the
    way towards the same-strategy specialist who had the best week. The
    knowledge transfer is numeric, not a sentence. Returns (intern, mentor)."""
    if not cfg.imitation_rate:
        return []
    trained = []
    for intern in alive:
        if intern.generation == 0 or intern.agent.get_params() is None:
            continue
        peers = [s for s in alive if s.generation == 0 and type(s.agent) is type(intern.agent)]
        scored = [(r, s) for s in peers
                  if (r := _week_return(journal, s.agent_id, day, cfg.week_days)) is not None]
        if not scored:
            continue
        best_ret, mentor = max(scored, key=lambda rs: rs[0])
        intern.agent.imitate(mentor.agent.get_params(), cfg.imitation_rate)
        prev = journal.load_params(intern.agent_id)
        journal.save_params(intern.agent_id, intern.agent.get_params(), prev[1] if prev else 0)
        journal.record_survival_event(day, intern.agent_id, "trained", best_ret,
                                      mentor.agent_id, intern.generation, intern.strategy,
                                      f"imitated {mentor.agent_id} ({best_ret:+.1%} this week) "
                                      f"at {cfg.imitation_rate:.0%}")
        trained.append((intern.agent_id, mentor.agent_id))
    return trained


def _consult_mentor(intern: Individual, day: int, alive: list[Individual],
                    journal: TradeJournal, tip_rate: float = 0.0) -> str | None:
    """An intern (any clone) who missed the target asks a senior for a tip
    and actually learns it: the mentor's most important lesson is copied
    into the intern's memory, and its parameters nudge towards the mentor's
    when they share a strategy. Founders never ask; they are the mentors.
    Returns the mentor's id, or None if nobody was consulted."""
    if intern.generation == 0:
        return None
    seniors = [i for i in alive if i.generation < intern.generation and i.alive
               and i.agent_id != intern.agent_id]
    if not seniors:
        return None
    parent = next((s for s in seniors if s.agent_id == intern.parent_id), None)
    same = [s for s in seniors if s.strategy == intern.strategy]
    mentor = parent or (same or seniors)[0]
    for candidate in (same or seniors):   # prefer the one on the longest streak
        if candidate.streak > mentor.streak:
            mentor = candidate
    tips = journal.lessons_for(mentor.agent_id, limit=1)
    if not tips:
        return None
    tip = tips[-1]
    intern.agent.learn([tip])
    if tip_rate and type(mentor.agent) is type(intern.agent) and mentor.agent.get_params():
        intern.agent.imitate(mentor.agent.get_params(), tip_rate)
    journal.add_lesson(intern.agent_id, day, f"tip from {mentor.agent_id}: {tip}")
    journal.record_survival_event(day, intern.agent_id, "consulted", 0.0,
                                  mentor.agent_id, intern.generation, intern.strategy, tip)
    return mentor.agent_id


def _try_clone(parent: Individual, day: int, equity: float, cfg: SurvivalConfig, rng,
               journal, next_id, population_size: int, mutate: bool = False) -> Individual | None:
    """A child is hired once the parent has grown its budget `clone_at`-fold
    (doubled it, by default) and is paid a full budget out of that profit,
    in cash — so a parent fully invested has to wait. It is a faithful copy
    of the parent (parameters, lessons, warmed-up indicators) unless this
    birth is an exploration one, in which case it is mutated."""
    if population_size >= cfg.max_population:
        return None
    wallet = parent.agent.wallet
    if equity < parent.budget * cfg.clone_at:
        return None
    child_budget = parent.budget
    if wallet.cash < child_budget:
        return None
    child_id = next_id(parent.agent_id.rsplit("-", 1)[0])
    child_agent = parent.agent.clone(child_id, child_budget, rng, mutate=mutate)
    if child_agent is None:
        return None
    wallet.cash -= child_budget
    child = Individual(child_agent, parent.strategy, child_budget, parent.agent_id,
                       parent.generation + 1, born_day=day)
    inherited = journal.lessons_for(parent.agent_id, limit=100)   # the whole book
    if child_agent.get_params() is None:
        # parameter agents already carry the lessons' effect in the copied
        # params; re-applying would double-count. LLM agents need the text.
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
                                  child.generation, child.strategy,
                                  "mutated (exploration)" if mutate else "faithful copy")
    return child
