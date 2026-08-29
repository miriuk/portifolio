from __future__ import annotations

import numpy as np

from ..agents.base import TradingAgent
from ..agents.llm import ClaudeTraderAgent
from ..learning.evolution import evolve_population
from ..learning.memory import TradeJournal
from ..learning.reflection import compute_stats, reflect_on_episode
from ..market.endogenous import EndogenousMarket
from ..market.synthetic import SyntheticMarket
from .episode import run_episode
from .leaderboard import leaderboard_table


def run_tournament(
    agents: list[TradingAgent],
    journal: TradeJournal,
    episodes: int = 5,
    steps_per_episode: int = 24 * 30,
    symbols: dict[str, float] | None = None,
    seed: int | None = None,
    evolve: bool = True,
    verbose: bool = True,
    market_factory=None,
    endogenous: bool = False,
) -> dict[str, list]:
    """The full learning loop:

    for each episode:
        fresh market, fresh wallets (memory persists!)
        run episode -> stats -> reflection -> lessons -> agent.learn()
        LLM agents additionally write their own reflection
        evolution: worst rule-agent inherits mutated params from the best
    """
    symbols = symbols or {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 150.0}
    rng = np.random.default_rng(seed)
    all_stats: dict[str, list] = {a.agent_id: [] for a in agents}
    full_curves: dict[str, list[float]] = {a.agent_id: [] for a in agents}
    agent_by_id = {a.agent_id: a for a in agents}

    # restore evolved parameters from previous runs (cross-run persistence)
    for agent in agents:
        saved = journal.load_params(agent.agent_id)
        if saved and agent.get_params() is not None:
            agent.set_params(saved[0])
        if isinstance(agent, ClaudeTraderAgent):
            lessons = journal.lessons_for(agent.agent_id)
            if lessons:
                agent.learn(lessons)

    for episode in range(1, episodes + 1):
        if verbose:
            print(f"\n=== episode {episode}/{episodes} ===")
        if market_factory is not None:
            market = market_factory(episode)
        elif endogenous:
            market = EndogenousMarket(symbols, seed=int(rng.integers(1 << 31)))
        else:
            market = SyntheticMarket(symbols, seed=int(rng.integers(1 << 31)))
        for agent in agents:
            agent.reset_wallet()
            agent.history.clear()

        result = run_episode(episode, market, agents, journal,
                             steps=steps_per_episode, verbose=verbose)

        episode_stats = []
        for agent in agents:
            curve = result.equity_curves[agent.agent_id]
            trades = journal.trades_for(agent.agent_id, episode)
            stats = compute_stats(agent.agent_id, episode, trades,
                                  start_equity=agent.starting_cash,
                                  end_equity=curve[-1] if curve else agent.starting_cash,
                                  max_drawdown=result.max_drawdown[agent.agent_id])
            episode_stats.append(stats)
            all_stats[agent.agent_id].append(stats)
            full_curves[agent.agent_id].extend(curve)

            lessons = reflect_on_episode(journal, stats)
            if isinstance(agent, ClaudeTraderAgent):
                closed = [t for t in trades if t.side == "sell" and t.pnl is not None]
                trades_text = "\n".join(
                    f"{t.symbol} {t.side} @ {t.price:.2f} pnl {t.pnl:+.2f} "
                    f"regime={t.regime} reason={t.reason}" for t in closed[-20:]
                ) or "(no closed trades)"
                stats_text = (f"return {stats.return_pct:+.1%}, win rate {stats.win_rate:.0%}, "
                              f"{stats.n_trades} trades, {stats.n_stop_losses} stop-losses, "
                              f"fees {stats.fees:.2f}, max drawdown {stats.max_drawdown:.0%}, "
                              f"pnl by regime {stats.pnl_by_regime}")
                reflection = agent.reflect(episode, stats_text, trades_text)
                if reflection:
                    journal.add_lesson(agent.agent_id, episode, reflection)
                    lessons.append(reflection)
            agent.learn(lessons)
            if verbose:
                flag = " [HALTED]" if result.halted[agent.agent_id] else ""
                print(f"  {agent.agent_id:<22} {stats.return_pct:+7.1%}  "
                      f"trades={stats.n_trades:<4} lessons={len(lessons)}{flag}")

        if evolve:
            log = evolve_population(
                journal, episode_stats,
                param_getter=lambda aid: agent_by_id[aid].get_params(),
                param_setter=lambda aid, p: agent_by_id[aid].set_params(p),
                rng=rng,
            )
            for line in log:
                if verbose:
                    print(f"  {line}")

        # persist current params every episode
        for agent in agents:
            params = agent.get_params()
            if params is not None:
                prev = journal.load_params(agent.agent_id)
                journal.save_params(agent.agent_id, params,
                                    prev[1] if prev else 0)

    if verbose:
        print("\n=== final leaderboard (all episodes) ===")
        print(leaderboard_table(all_stats, full_curves))
    return {"stats": all_stats, "curves": full_curves}
