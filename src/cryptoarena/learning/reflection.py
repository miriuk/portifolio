from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .memory import TradeJournal, TradeRecord


@dataclass
class EpisodeStats:
    agent_id: str
    episode: int
    start_equity: float
    end_equity: float
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_stop_losses: int = 0
    fees: float = 0.0
    max_drawdown: float = 0.0
    pnl_by_regime: dict[str, float] = field(default_factory=dict)
    market_return: float | None = None      # equal-weight move of the tape over the episode

    @property
    def return_pct(self) -> float:
        if self.start_equity <= 0:
            return 0.0
        return (self.end_equity - self.start_equity) / self.start_equity

    @property
    def win_rate(self) -> float:
        closed = self.n_wins + self.n_losses
        return self.n_wins / closed if closed else 0.0


def compute_stats(agent_id: str, episode: int, trades: list[TradeRecord],
                  start_equity: float, end_equity: float,
                  max_drawdown: float, market_return: float | None = None) -> EpisodeStats:
    stats = EpisodeStats(agent_id, episode, start_equity, end_equity,
                         max_drawdown=max_drawdown, market_return=market_return)
    by_regime: dict[str, float] = defaultdict(float)
    for t in trades:
        stats.n_trades += 1
        stats.fees += t.fee
        if t.side == "sell" and t.pnl is not None:
            if t.pnl > 0:
                stats.n_wins += 1
            else:
                stats.n_losses += 1
            if t.reason == "risk:stop_loss":
                stats.n_stop_losses += 1
            if t.regime:
                by_regime[t.regime] += t.pnl
    stats.pnl_by_regime = dict(by_regime)
    return stats


def reflect_on_episode(journal: TradeJournal, stats: EpisodeStats) -> list[str]:
    """Turn an episode's raw outcomes into explicit, persisted lessons.

    Heuristic post-mortem shared by all agent types; the LLM agent adds
    its own Claude-written reflection on top (see agents/llm.py).
    """
    lessons: list[str] = []
    s = stats
    if s.n_stop_losses >= 3:
        lessons.append(
            f"episode {s.episode}: hit {s.n_stop_losses} stop-losses — entries are "
            "too aggressive or too early; demand stronger confirmation before buying."
        )
    if s.return_pct <= 0 and s.fees > s.start_equity * 0.01:
        lessons.append(
            f"episode {s.episode}: fees ({s.fees:.2f}) ate into a losing episode — "
            "overtrading; trade less often or with more conviction."
        )
    # Sitting out is a decision, not a fault: capital kept in a falling market
    # is a win. Only a market that ran without us earns the "loosen up" note.
    if s.n_trades <= 2 and s.market_return is not None and s.market_return > 0.03 \
            and s.return_pct < s.market_return / 3:
        lessons.append(
            f"episode {s.episode}: the market moved {s.market_return:+.1%} and we made "
            f"{s.return_pct:+.1%} with {s.n_trades} trades — missed the move; "
            "loosen entry conditions slightly."
        )
    if s.max_drawdown > 0.30:
        lessons.append(
            f"episode {s.episode}: drawdown reached {s.max_drawdown:.0%} — "
            "position sizing too large for current volatility."
        )
    regime_of: dict[str, str] = {}
    for regime, pnl in sorted(s.pnl_by_regime.items(), key=lambda kv: kv[1]):
        if pnl < -s.start_equity * 0.02:
            text = (
                f"episode {s.episode}: lost {pnl:.2f} trading in '{regime}' regime — "
                f"this strategy is mismatched to '{regime}'; reduce activity there."
            )
            lessons.append(text)
            regime_of[text] = regime
    if s.return_pct > 0.05 and s.win_rate > 0.55:
        best = max(s.pnl_by_regime, key=s.pnl_by_regime.get) if s.pnl_by_regime else None
        if best:
            text = (
                f"episode {s.episode}: +{s.return_pct:.1%} with {s.win_rate:.0%} win rate, "
                f"strongest in '{best}' regime — lean into this setup."
            )
            lessons.append(text)
            regime_of[text] = best
    for lesson in lessons:
        journal.add_lesson(s.agent_id, s.episode, lesson,
                           regime=regime_of.get(lesson, ""))
    return lessons
