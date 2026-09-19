"""Physical / emotional / mental state of each agent, derived from what
actually happened to it in the market — nothing here is random.

    energy     (physical)  drained by trading activity and drawdown, restored by quiet days
    stress     (emotional) losses, stop-losses, missed targets, closeness to the line,
                           and colleagues being let go
    focus      (mental)    lessons learned, win rate, target streaks; eroded by stress
    motivation (drive)     a colleague let go is a warning AND a spur; parties and praise
                           lift it; long miss streaks wear it down
    ego        (self)      employee-of-the-week frames, party praise and streaks

The world renderer turns these into behaviour (rest, pace, study, celebrate)
and into what the agents say to each other. The chatter itself is not
stored anywhere — it is composed on the fly from this state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

WINDOW_DAYS = 3


@dataclass
class AgentVitals:
    agent_id: str
    strategy: str
    alive: bool
    generation: int
    parent_id: str | None
    equity: float
    budget: float
    day_return: float          # latest day's return
    window_return: float       # return over the last WINDOW_DAYS days
    trades_today: int
    stop_losses: int
    win_rate: float
    streak: int
    misses: int
    lessons: int
    last_reason: str           # why it last traded (fuel for chatter)
    last_side: str
    last_symbol: str
    regime: str                # regime at its last trade
    role: str                  # "specialist" (founder) or "intern" (clone under test)
    mentor: str | None         # who it last asked for a tip
    tip: str                   # the tip it received
    energy: float
    stress: float
    focus: float
    motivation: float
    ego: float
    parties: int               # happy hours earned in the last two weeks
    awards: int                # employee-of-the-week frames (recent)
    immune_until: int          # cannot be let go until this day (0 = no immunity)
    spared: int                # times immunity saved it from dismissal (recent)
    mood: str
    activity: str

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _strategy_of(agent_id: str) -> str:
    return agent_id.rsplit("-", 1)[0]


def compute_vitals(summary: pd.DataFrame, trades: pd.DataFrame, lessons: pd.DataFrame,
                   survival: pd.DataFrame) -> list[AgentVitals]:
    """One AgentVitals per agent seen in the journal, computed from the
    last few days of episode summaries, trades, lessons and survival events."""
    if summary.empty and survival.empty:
        return []
    agent_ids: list[str] = []
    for frame in (survival, summary):
        if not frame.empty:
            for aid in frame["agent_id"]:
                if aid not in agent_ids:
                    agent_ids.append(aid)

    dead = set(survival.loc[survival["event"] == "died", "agent_id"]) if not survival.empty else set()
    born = (survival[survival["event"] == "born"].drop_duplicates("agent_id")
            .set_index("agent_id") if not survival.empty else pd.DataFrame())
    last_day = int(summary["episode"].max()) if not summary.empty else 0
    # a dismissal in the last few days is felt by everyone who stayed
    recent_dismissals = 0
    if not survival.empty:
        recent_dismissals = int(((survival["event"] == "died")
                                 & (survival["day"] >= last_day - 3)).sum())

    vitals = []
    for aid in agent_ids:
        rows = summary[summary["agent_id"] == aid].sort_values("episode") if not summary.empty \
            else pd.DataFrame()
        recent = rows.tail(WINDOW_DAYS)
        latest = rows.iloc[-1] if len(rows) else None
        equity = float(latest["end_equity"]) if latest is not None else (
            float(born.loc[aid, "equity"]) if aid in born.index else 0.0)
        budget = float(born.loc[aid, "equity"]) if aid in born.index else (
            float(rows.iloc[0]["start_equity"]) if len(rows) else equity)
        day_return = float((latest["end_equity"] / latest["start_equity"]) - 1) \
            if latest is not None and latest["start_equity"] > 0 else 0.0
        window_return = float((recent["end_equity"] / recent["start_equity"]).prod() - 1) \
            if len(recent) and (recent["start_equity"] > 0).all() else 0.0
        trades_today = int(latest["n_trades"]) if latest is not None else 0
        stop_losses = int(recent["n_stop_losses"].sum()) if len(recent) else 0
        wins, losses = (int(recent["n_wins"].sum()), int(recent["n_losses"].sum())) \
            if len(recent) else (0, 0)
        win_rate = wins / (wins + losses) if wins + losses else 0.5
        max_dd = float(recent["max_drawdown"].max()) if len(recent) else 0.0
        quiet_days = int((recent["n_trades"] == 0).sum()) if len(recent) else 0

        streak = misses = parties = awards = immune_until = spared = 0
        mentor, tip = None, ""
        if not survival.empty:
            mine = survival[survival["agent_id"] == aid]
            immunities = mine[mine["event"] == "immune"]
            if not immunities.empty:
                until = int(str(immunities.iloc[-1]["detail"]).rsplit(" ", 1)[-1] or 0)
                immune_until = until if until >= last_day else 0
            spared = int(((mine["event"] == "spared") & (mine["day"] >= last_day - 3)).sum())
            parties = int(((mine["event"] == "party") & (mine["day"] >= last_day - 14)).sum())
            awards = int(((mine["event"] == "employee_of_week")
                          & (mine["day"] >= last_day - 21)).sum())
            consulted = mine[mine["event"] == "consulted"]
            if not consulted.empty:
                mentor = str(consulted.iloc[-1]["parent_id"])
                tip = str(consulted.iloc[-1]["detail"] or "")
            hits = mine[mine["event"] == "target_hit"]
            days_with_hit = set(hits["day"])
            born_day = int(born.loc[aid, "day"]) if aid in born.index else 0
            for d in range(last_day, born_day, -1):   # only days it was actually here
                if d in days_with_hit:
                    break
                misses += 1
            if not hits.empty and int(hits.iloc[-1]["day"]) == last_day:
                streak = int(str(hits.iloc[-1]["detail"]).replace("streak", "").strip() or 1)
        n_lessons = int((lessons["agent_id"] == aid).sum()) if not lessons.empty else 0
        importance = float(lessons.loc[lessons["agent_id"] == aid, "importance"].sum()) \
            if not lessons.empty else 0.0
        my_trades = trades[trades["agent_id"] == aid] if not trades.empty else pd.DataFrame()
        last_trade = my_trades.iloc[0] if len(my_trades) else None  # trades are newest-first

        alive = aid not in dead
        ratio = equity / budget if budget > 0 else 1.0
        energy = _clamp(1.0 - 0.06 * int(recent["n_trades"].sum() if len(recent) else 0)
                        - 0.6 * max_dd + 0.12 * quiet_days)
        is_intern = aid in born.index and int(born.loc[aid, "generation"]) > 0
        safe = (not is_intern) or immune_until > 0
        worry = recent_dismissals * (0.05 if safe else 0.12)        # the safe ones sleep
        stress = _clamp(0.15 + 0.12 * stop_losses + 3.0 * max(0.0, -window_return)
                        + (0.0 if safe else 1.2) * max(0.0, 0.85 - ratio) + 0.06 * min(misses, 6)
                        - 0.15 * (win_rate - 0.5) + worry - 0.08 * parties + 0.15 * spared)
        motivation = _clamp(0.45 + 0.15 * recent_dismissals + 0.2 * parties + 0.1 * streak
                            - 0.04 * min(misses, 8) + 0.1 * awards + 0.2 * spared
                            - (0.05 if immune_until else 0.0))          # a little complacency
        ego = _clamp(0.25 + 0.3 * awards + 0.15 * parties + 0.08 * streak
                     + (0.15 if window_return > 0.02 else 0.0) - 0.05 * min(misses, 4)
                     + (0.05 if immune_until else 0.0))
        focus = _clamp(0.35 + 0.05 * n_lessons + 0.04 * importance + 0.25 * (win_rate - 0.5)
                       + 0.08 * streak - 0.35 * stress + 0.1 * (motivation - 0.5))
        if not alive:
            mood, activity = "dead", "dead"
        elif stress > 0.75:
            mood, activity = "panicking", "pacing"
        elif energy < 0.3:
            mood, activity = "exhausted", "resting"
        elif ego > 0.7 and stress < 0.5:
            mood, activity = "proud", "celebrating" if parties else "trading"
        elif stress > 0.5 and motivation > 0.6:
            mood, activity = "determined", "trading"
        elif stress > 0.5:
            mood, activity = "anxious", "pacing" if trades_today == 0 else "trading"
        elif window_return > 0.02 and stress < 0.4:
            mood, activity = "euphoric", "celebrating"
        elif window_return > 0:
            mood, activity = "confident", "trading" if trades_today else "studying"
        else:
            mood, activity = "calm", "studying" if n_lessons else "watching"

        vitals.append(AgentVitals(
            agent_id=aid, strategy=_strategy_of(aid), alive=alive,
            generation=int(born.loc[aid, "generation"]) if aid in born.index else 0,
            parent_id=(born.loc[aid, "parent_id"] if aid in born.index
                       and isinstance(born.loc[aid, "parent_id"], str) else None),
            equity=round(equity, 2), budget=round(budget, 2),
            day_return=round(day_return, 4), window_return=round(window_return, 4),
            trades_today=trades_today, stop_losses=stop_losses, win_rate=round(win_rate, 2),
            streak=streak, misses=misses, lessons=n_lessons,
            last_reason=str(last_trade["reason"]) if last_trade is not None else "",
            last_side=str(last_trade["side"]) if last_trade is not None else "",
            last_symbol=str(last_trade["symbol"]) if last_trade is not None else "",
            regime=str(last_trade["regime"] or "") if last_trade is not None else "",
            role="intern" if (aid in born.index and int(born.loc[aid, "generation"]) > 0)
            else "specialist",
            mentor=mentor, tip=tip,
            energy=round(energy, 2), stress=round(stress, 2), focus=round(focus, 2),
            motivation=round(motivation, 2), ego=round(ego, 2), parties=parties, awards=awards,
            immune_until=immune_until, spared=spared,
            mood=mood, activity=activity,
        ))
    return vitals
