from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents.llm import ClaudeTraderAgent
from .agents.rules import (BreakoutAgent, MeanReversionAgent, MomentumAgent,
                           RegimeSwitchAgent, VolTargetAgent)
from .arena.tournament import run_tournament
from .learning.memory import TradeJournal


def build_agents(cash: float, with_llm: bool, llm_model: str, journal=None,
                 debate: bool = False) -> list:
    agents = [
        MomentumAgent("momentum-1", cash),
        MomentumAgent("momentum-2", cash, params={"lookback": 48, "entry_threshold": 0.035}),
        MeanReversionAgent("meanrev-1", cash),
        MeanReversionAgent("meanrev-2", cash, params={"lookback": 96, "entry_threshold": 0.06}),
        BreakoutAgent("breakout-1", cash),
        RegimeSwitchAgent("regime-1", cash),
        VolTargetAgent("voltarget-1", cash),
    ]
    if with_llm:
        if ClaudeTraderAgent.available():
            agents.append(ClaudeTraderAgent("claude-trader", cash, model=llm_model,
                                            journal=journal, debate=debate))
        else:
            print("warning: no ANTHROPIC_API_KEY / auth profile found — "
                  "running without the LLM agent (rule agents still learn).")
    return agents


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cryptoarena",
        description="Simulated crypto arena where trading agents compete and learn.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a learning tournament")
    run.add_argument("--episodes", type=int, default=5)
    run.add_argument("--steps", type=int, default=24 * 30,
                     help="hourly bars per episode (default: one month)")
    run.add_argument("--cash", type=float, default=10_000.0)
    run.add_argument("--db", default="arena.db", help="journal database path")
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--llm", action="store_true",
                     help="include the Claude trader agent (needs API credentials)")
    run.add_argument("--llm-model", default="claude-opus-5")
    run.add_argument("--debate", action="store_true",
                     help="LLM agent runs a bull/bear debate before each "
                          "decision (3 extra API calls per decision)")
    run.add_argument("--no-evolve", action="store_true")
    run.add_argument("--endogenous", action="store_true",
                     help="agents trade against a shared order book and "
                          "move prices with their own orders")

    surv = sub.add_parser("survive", help="survival colony: daily target, death, cloning")
    surv.add_argument("--days", type=int, default=30)
    surv.add_argument("--budget", type=float, default=5.0,
                      help="starting cash per founder (and per clone)")
    surv.add_argument("--clone-at", type=float, default=1.1,
                      help="hire a clone once equity reaches this multiple of the budget")
    surv.add_argument("--target", type=float, default=0.005,
                      help="daily return needed to earn the right to clone")
    surv.add_argument("--death", type=float, default=0.6,
                      help="dead when equity falls below this fraction of own budget")
    surv.add_argument("--cost", type=float, default=0.001,
                      help="daily cost of living as a fraction of own budget")
    surv.add_argument("--pressure", type=float, default=0.0,
                      help="after each missed target, scale order size by (1+pressure)")
    surv.add_argument("--max-pop", type=int, default=12)
    surv.add_argument("--db", default="arena.db")
    surv.add_argument("--seed", type=int, default=None)
    surv.add_argument("--llm", action="store_true")
    surv.add_argument("--llm-model", default="claude-opus-5")
    surv.add_argument("--synthetic", action="store_true",
                      help="use the synthetic price generator instead of the order book")

    lessons = sub.add_parser("lessons", help="show an agent's learned lessons")
    lessons.add_argument("agent_id")
    lessons.add_argument("--db", default="arena.db")
    lessons.add_argument("--limit", type=int, default=20)

    reset = sub.add_parser("reset", help="wipe the journal (start learning from zero)")
    reset.add_argument("--db", default="arena.db")

    dash = sub.add_parser("dashboard", help="launch a live web dashboard (Streamlit)")
    dash.add_argument("--db", default="arena.db")
    dash.add_argument("--port", type=int, default=8501)

    args = parser.parse_args()

    if args.command == "run":
        journal = TradeJournal(args.db)
        agents = build_agents(args.cash, args.llm, args.llm_model, journal=journal,
                              debate=args.debate)
        try:
            run_tournament(agents, journal, episodes=args.episodes,
                           steps_per_episode=args.steps, seed=args.seed,
                           evolve=not args.no_evolve,
                           endogenous=args.endogenous)
        finally:
            journal.close()
    elif args.command == "survive":
        from .arena.survival import SurvivalConfig, run_survival
        journal = TradeJournal(args.db)
        founders = build_agents(args.budget, args.llm, args.llm_model, journal=journal)
        try:
            res = run_survival(founders, journal, SurvivalConfig(
                days=args.days, budget=args.budget, daily_target=args.target,
                death_below=args.death, daily_cost=args.cost, clone_at=args.clone_at,
                pressure=args.pressure, max_population=args.max_pop,
                seed=args.seed, endogenous=not args.synthetic))
            print(f"\n{len(res.alive)} of {len(res.population)} agents alive after "
                  f"{len(res.alive_per_day)} days; colony equity "
                  f"{res.equity_per_day[-1] if res.equity_per_day else 0:,.0f}")
        finally:
            journal.close()
    elif args.command == "lessons":
        journal = TradeJournal(args.db)
        try:
            found = journal.lessons_for(args.agent_id, args.limit)
            if not found:
                print(f"no lessons recorded for {args.agent_id}")
            for lesson in found:
                print(f"- {lesson}")
        finally:
            journal.close()
    elif args.command == "reset":
        path = Path(args.db)
        if path.exists():
            path.unlink()
            print(f"removed {path}")
        else:
            print(f"{path} does not exist")
    elif args.command == "dashboard":
        import subprocess
        try:
            import streamlit  # noqa: F401
        except ImportError:
            print("Streamlit isn't installed. Run: pip install -e \".[ui]\"")
            raise SystemExit(1)
        dashboard_path = Path(__file__).parent / "dashboard.py"
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(dashboard_path),
            "--server.port", str(args.port),
            "--", "--db", args.db,
        ])


if __name__ == "__main__":
    main()
