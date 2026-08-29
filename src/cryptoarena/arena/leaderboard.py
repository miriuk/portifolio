from __future__ import annotations

import numpy as np

from ..learning.reflection import EpisodeStats


def sharpe(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    eq = np.asarray(equity_curve)
    rets = np.diff(eq) / np.maximum(eq[:-1], 1e-9)
    if rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(24 * 365))  # annualized, hourly bars


def leaderboard_table(all_stats: dict[str, list[EpisodeStats]],
                      equity_curves: dict[str, list[float]] | None = None) -> str:
    """Cumulative leaderboard across every episode played so far."""
    rows = []
    for agent_id, stats in all_stats.items():
        total_ret = 1.0
        for s in stats:
            total_ret *= (1 + s.return_pct)
        n_trades = sum(s.n_trades for s in stats)
        wins = sum(s.n_wins for s in stats)
        losses = sum(s.n_losses for s in stats)
        win_rate = wins / (wins + losses) if wins + losses else 0.0
        max_dd = max((s.max_drawdown for s in stats), default=0.0)
        sr = sharpe(equity_curves.get(agent_id, [])) if equity_curves else 0.0
        rows.append((agent_id, total_ret - 1, sr, win_rate, n_trades, max_dd))
    rows.sort(key=lambda r: r[1], reverse=True)
    lines = [
        f"{'agent':<22} {'return':>8} {'sharpe':>7} {'win%':>6} {'trades':>7} {'maxDD':>6}",
        "-" * 60,
    ]
    for agent_id, ret, sr, wr, nt, dd in rows:
        lines.append(f"{agent_id:<22} {ret:>+7.1%} {sr:>7.2f} {wr:>6.0%} {nt:>7d} {dd:>6.0%}")
    return "\n".join(lines)
