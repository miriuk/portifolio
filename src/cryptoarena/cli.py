from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents.llm import ClaudeTraderAgent
from .arena.tournament import run_tournament
from .learning.memory import TradeJournal


def build_agents(cash: float, with_llm: bool, llm_model: str, journal=None,
                 debate: bool = False, floor: str = "crypto") -> list:
    from .floors import get_floor
    agents = get_floor(floor).build_founders(cash)
    if with_llm:
        if ClaudeTraderAgent.available():
            agents.append(ClaudeTraderAgent("claude-trader", cash, model=llm_model,
                                            journal=journal, debate=debate))
        else:
            print("warning: no ANTHROPIC_API_KEY / auth profile found — "
                  "running without the LLM agent (rule agents still learn).")
    return agents


def _live(args) -> None:
    import json

    from .arena.live_colony import LiveColony
    from .arena.survival import SurvivalConfig
    from .floors import get_floor

    floor = get_floor(args.floor)
    args.db = args.db or floor.default_db
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    journal = TradeJournal(args.db)
    try:
        if args.status:
            saved = journal.load_state("live_colony")
            if saved is None:
                print("no live colony in", args.db)
                return
            feed = _StaticFeed(saved.get("timeframe", "1h"), saved.get("exchange", ""),
                               saved.get("symbols", []))
            colony = LiveColony.open(journal, [], SurvivalConfig(), feed, verbose=False)
            print(json.dumps(colony.status(), indent=2))
            return
        symbols = None
        if args.symbols:
            symbols = dict(pair.split("=", 1) for pair in args.symbols.split(","))
        feed_kw = {"symbols": symbols}
        if args.exchange:
            feed_kw["exchange_id"] = args.exchange
        if args.timeframe:
            feed_kw["timeframe"] = args.timeframe
        feed = floor.make_feed(**feed_kw)
        cfg = floor.config(days=args.days, **_overrides(args))
        founders = build_agents(cfg.budget, False, "", floor=floor.name)
        founding = journal.load_state("live_colony") is None
        colony = LiveColony.open(journal, founders, cfg, feed,
                                 warmup=args.warmup or floor.warmup)
        if args.once:
            n = 1 if founding else colony.run_once()
            if hasattr(feed, "min_costs"):              # real-money readiness, refreshed each tick
                colony.min_costs = feed.min_costs(colony.last_prices) or colony.min_costs
                colony.save()
            s = colony.status()
            print(("founded the colony on " if founding else "processed ")
                  + f"{n} new candle(s); day {s['day']} h{s['hour']}, "
                  f"{s['alive']} alive ({s['interns']} interns), colony {s['colony_equity']:.2f}")
        else:
            colony.run_forever(args.days)
    finally:
        journal.close()


_OVERRIDES = {"budget": "budget", "target": "daily_target", "death": "death_below",
              "cost": "daily_cost", "clone_at": "clone_at", "min_child": "min_child_budget",
              "pressure": "pressure", "max_pop": "max_population", "seed": "seed",
              "fee": "fee_rate", "learn": "learn"}


def _overrides(args) -> dict:
    """Only the survival knobs the user actually set; the floor supplies the rest."""
    out = {}
    for flag, field in _OVERRIDES.items():
        value = getattr(args, flag, None)
        if value is not None:
            out[field] = bool(value) if field == "learn" else value
    return out


class _StaticFeed:
    """Enough of a feed to reopen a saved colony without touching the network."""

    def __init__(self, timeframe: str, exchange_id: str, symbols: list[str]):
        from .market.live import TIMEFRAME_SECONDS
        self.timeframe, self.exchange_id = timeframe, exchange_id
        self.symbols = {s: s for s in symbols}
        self.seconds = TIMEFRAME_SECONDS.get(timeframe, 3600)

    def aligned(self, limit: int = 0, since=None):
        return []


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
                      help="hire a clone once equity reaches this multiple of the budget; "
                           "the child is born with the surplus")
    surv.add_argument("--min-child", type=float, default=0.2,
                      help="smallest surplus (quote units) that becomes a child")
    surv.add_argument("--target", type=float, default=0.005,
                      help="daily return needed to earn the right to clone")
    surv.add_argument("--death", type=float, default=0.6,
                      help="dead when equity falls below this fraction of own budget")
    surv.add_argument("--cost", type=float, default=0.0002,
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

    live = sub.add_parser("live", help="survival colony on real market data (paper trading)")
    live.add_argument("--floor", default="crypto", choices=["crypto", "stocks"],
                      help="which floor of the building: crypto (hourly, Kraken) or "
                           "stocks (daily, Stooq)")
    live.add_argument("--db", default=None, help="journal path (default: the floor's)")
    live.add_argument("--exchange", default=None,
                      help="CCXT exchange id for public candles (kraken, coinbase, binance…)")
    live.add_argument("--timeframe", default=None)
    live.add_argument("--symbols", default=None,
                      help="comma list of ARENA=CCXT pairs, e.g. BTCUSD=BTC/USD,ETHUSD=ETH/USD")
    live.add_argument("--once", action="store_true",
                      help="process the candles that closed since the last run, save, exit "
                           "(for cron / GitHub Actions)")
    live.add_argument("--days", type=int, default=7,
                      help="without --once: stay up and tick hourly for this many days")
    live.add_argument("--status", action="store_true", help="print the colony's state as JSON")
    live.add_argument("--warmup", type=int, default=None,
                      help="closed candles of history the founders start with")
    for flag, help_ in [("--budget", "cash per founder (5)"), ("--clone-at", "hire at × budget (1.1)"),
                        ("--min-child", "smallest child (0.2)"), ("--target", "daily target (crypto 0.5%%, stocks 0.2%%)"),
                        ("--death", "let go below this × budget (0.6)"), ("--cost", "cost of living/day (0.02%%)"),
                        ("--fee", "taker fee per side (crypto 0.26%%, stocks 0.05%%)"), ("--pressure", "after a miss (0)")]:
        live.add_argument(flag, type=float, default=None, help=help_)
    live.add_argument("--learn", type=int, default=None, help="1 = nightly reflection nudges params")
    live.add_argument("--max-pop", type=int, default=None)
    live.add_argument("--seed", type=int, default=None)

    bt = sub.add_parser("backtest", help="walk-forward survival colonies on real candles")
    bt.add_argument("--floor", default="crypto", choices=["crypto", "stocks"])
    bt.add_argument("--data", default=None, help="directory of ReplayMarket CSVs (default: the floor's)")
    bt.add_argument("--days", type=int, default=None, help="colony days per window (crypto 30, stocks 60)")
    bt.add_argument("--stride", type=int, default=None, help="days between window starts")
    bt.add_argument("--windows", type=int, default=None, help="only the last N windows")
    bt.add_argument("--aligned", action="store_true",
                    help="a fixed universe: only the bars every coin has (crypto grows by default)")
    bt.add_argument("--warmup", type=int, default=None, help="bars before day 1 (crypto 720, stocks 250)")
    for flag in ("--fee", "--budget", "--clone-at", "--min-child", "--target", "--death", "--cost",
                 "--pressure"):
        bt.add_argument(flag, type=float, default=None)
    bt.add_argument("--learn", type=int, default=None)
    bt.add_argument("--max-pop", type=int, default=None)
    bt.add_argument("--seed", type=int, default=1)
    bt.add_argument("--quiet", action="store_true")

    lessons = sub.add_parser("lessons", help="show an agent's learned lessons")
    lessons.add_argument("agent_id")
    lessons.add_argument("--db", default="arena.db")
    lessons.add_argument("--limit", type=int, default=20)

    reset = sub.add_parser("reset", help="wipe the journal (start learning from zero)")
    reset.add_argument("--db", default="arena.db")

    dash = sub.add_parser("dashboard", help="launch a live web dashboard (Streamlit)")
    dash.add_argument("--db", default="arena.db")
    dash.add_argument("--db-url", default="", help="read a journal published at a URL")
    dash.add_argument("--live", action="store_true",
                      help="show the colony the hourly GitHub job publishes")
    dash.add_argument("--floor", default="crypto", choices=["crypto", "stocks"],
                      help="with --live: which floor to open first")
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
                min_child_budget=args.min_child,
                pressure=args.pressure, max_population=args.max_pop,
                seed=args.seed, endogenous=not args.synthetic))
            print(f"\n{len(res.alive)} of {len(res.population)} agents alive after "
                  f"{len(res.alive_per_day)} days; colony equity "
                  f"{res.equity_per_day[-1] if res.equity_per_day else 0:,.0f}")
        finally:
            journal.close()
    elif args.command == "live":
        _live(args)
    elif args.command == "backtest":
        from .arena.backtest import (format_by_year, format_summary, load_sentiment, load_tape,
                                     run_backtest)
        from .floors import get_floor
        floor = get_floor(args.floor)
        # crypto: the universe grows with the years (a coin joins at its listing)
        tape = load_tape(args.data or floor.data_dir, align=args.aligned or floor.name != "crypto")
        sentiment = load_sentiment(args.data or floor.data_dir) if floor.name == "crypto" else {}
        cfg = floor.config(**_overrides(args))
        report = run_backtest(tape, lambda: build_agents(cfg.budget, False, "", floor=floor.name),
                              cfg, days=args.days or floor.backtest_days,
                              stride_days=args.stride or floor.backtest_stride,
                              warmup_bars=args.warmup or (720 if floor.name == "crypto" else 250),
                              max_windows=args.windows, verbose=not args.quiet,
                              sentiment=sentiment or None)
        print()
        print(format_summary(report.summary()))
        years = report.by_year()
        if len(years) > 1:
            print()
            print(format_by_year(years, ("bear-1",)))
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
        extra = (["--live"] if args.live else []) + ["--floor", args.floor] + \
            (["--db-url", args.db_url] if args.db_url else [])
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(dashboard_path),
            "--server.port", str(args.port),
            "--", "--db", args.db, *extra,
        ])


if __name__ == "__main__":
    main()
