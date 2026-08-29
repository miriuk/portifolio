from __future__ import annotations

import argparse
from pathlib import Path

from .agents.llm import ClaudeTraderAgent
from .agents.rules import BreakoutAgent, MeanReversionAgent, MomentumAgent
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

    lessons = sub.add_parser("lessons", help="show an agent's learned lessons")
    lessons.add_argument("agent_id")
    lessons.add_argument("--db", default="arena.db")
    lessons.add_argument("--limit", type=int, default=20)

    reset = sub.add_parser("reset", help="wipe the journal (start learning from zero)")
    reset.add_argument("--db", default="arena.db")

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


if __name__ == "__main__":
    main()
