from __future__ import annotations

import numpy as np

from .memory import TradeJournal
from .reflection import EpisodeStats


def evolve_population(
    journal: TradeJournal,
    stats: list[EpisodeStats],
    param_getter,
    param_setter,
    mutation_scale: float = 0.15,
    rng: np.random.Generator | None = None,
) -> list[str]:
    """Tournament selection: the worst agent adopts a mutated copy of the
    best agent's parameters. Returns log lines describing what changed.

    param_getter(agent_id) -> dict of tunable params (numeric values only)
    param_setter(agent_id, params) -> apply params to the live agent
    """
    rng = rng or np.random.default_rng()
    log: list[str] = []
    evolvable = [s for s in stats if param_getter(s.agent_id) is not None]
    if len(evolvable) < 2:
        return log
    ranked = sorted(evolvable, key=lambda s: s.return_pct, reverse=True)
    best, worst = ranked[0], ranked[-1]
    if best.agent_id == worst.agent_id or best.return_pct <= worst.return_pct:
        return log
    # only replace a clearly losing agent — don't churn near-ties
    if worst.return_pct > -0.01 and (best.return_pct - worst.return_pct) < 0.05:
        return log
    parent = param_getter(best.agent_id)
    mutated = {}
    for key, value in parent.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            factor = 1 + rng.standard_normal() * mutation_scale
            mutated[key] = type(value)(value * factor) if value != 0 else value
        else:
            mutated[key] = value
    param_setter(worst.agent_id, mutated)
    prev = journal.load_params(worst.agent_id)
    generation = (prev[1] if prev else 0) + 1
    journal.save_params(worst.agent_id, mutated, generation)
    journal.add_lesson(
        worst.agent_id, worst.episode,
        f"episode {worst.episode}: returned {worst.return_pct:.1%} (worst of cohort); "
        f"adopted mutated parameters from {best.agent_id} "
        f"({best.return_pct:+.1%}), generation {generation}.",
    )
    log.append(
        f"evolution: {worst.agent_id} ({worst.return_pct:+.1%}) inherits mutated params "
        f"from {best.agent_id} ({best.return_pct:+.1%}) -> gen {generation}"
    )
    return log
