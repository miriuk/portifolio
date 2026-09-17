"""Live web dashboard for CryptoArena — watch a run as it happens.

Run with:
    cryptoarena dashboard              # launches this via streamlit for you
    streamlit run streamlit_app.py     # what Streamlit Community Cloud runs

The page only *reads* the journal (WAL mode lets it do that safely while a
tournament is writing to the same file). The tournament itself can come from
`cryptoarena run` in another terminal or from the sidebar, which runs it on a
background thread inside this process — the only option on a hosted deploy.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

import streamlit.components.v1 as components

from cryptoarena.agents.llm import ClaudeTraderAgent
from cryptoarena.arena import background
from cryptoarena.arena.background import RunConfig
from cryptoarena.world.render import build_state, render_world


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="arena.db")
    # Streamlit's CLI consumes its own flags and the "--" separator itself,
    # so by the time the script runs, sys.argv[1:] is already just our args.
    return parser.parse_args(sys.argv[1:])


def _read_table(conn: sqlite3.Connection, query: str) -> pd.DataFrame:
    try:
        return pd.read_sql_query(query, conn)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return pd.DataFrame()


def load_data(db_path: str) -> dict[str, pd.DataFrame]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            "equity": _read_table(conn, "SELECT * FROM equity_snapshots"),
            "summary": _read_table(conn, "SELECT * FROM episode_summary"),
            "trades": _read_table(conn, "SELECT * FROM trades ORDER BY id DESC LIMIT 300"),
            "lessons": _read_table(
                conn, "SELECT * FROM lessons ORDER BY importance DESC, id DESC LIMIT 150"),
            "survival": _read_table(conn, "SELECT * FROM survival_events ORDER BY id"),
            "market": _read_table(
                conn, "SELECT * FROM market_snapshots ORDER BY episode DESC, step DESC LIMIT 600"),
        }
    finally:
        conn.close()


def lineage_dot(events: pd.DataFrame) -> str:
    """Graphviz source for the family tree: one node per agent ever born,
    edges parent -> child, the dead greyed out with their day of death."""
    palette = {"momentum": "#f7931a", "meanreversion": "#3b82f6", "breakout": "#22c55e",
               "claudetrader": "#a855f7"}
    born = events[events["event"] == "born"]
    died = events[events["event"] == "died"].set_index("agent_id")["day"]
    latest_equity = events.groupby("agent_id")["equity"].last()
    lines = ["digraph lineage {", "  rankdir=LR; bgcolor=transparent;",
             '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
             'fontsize=11, color="#00000000"];',
             '  edge [color="#888888"];']
    for _, r in born.iterrows():
        aid = r["agent_id"]
        color = palette.get(r["strategy"], "#94a3b8")
        if aid in died.index:
            label = f"{aid}\\nlet go · day {int(died[aid])}"
            lines.append(f'  "{aid}" [label="{label}", fillcolor="#3f3f46", fontcolor="#a1a1aa"];')
        else:
            label = f"{aid}\\ngen {int(r['generation'])} · {latest_equity[aid]:,.0f}"
            lines.append(f'  "{aid}" [label="{label}", fillcolor="{color}", fontcolor="white"];')
        if isinstance(r["parent_id"], str) and r["parent_id"]:
            lines.append(f'  "{r["parent_id"]}" -> "{aid}" [label="day {int(r["day"])}", '
                         'fontsize=9, fontcolor="#888888"];')
    lines.append("}")
    return "\n".join(lines)


def colony_view(events: pd.DataFrame) -> None:
    alive_ids = set(events.loc[events["event"] == "born", "agent_id"]) - \
        set(events.loc[events["event"] == "died", "agent_id"])
    survived = events[events["event"] == "survived"]
    last_day = int(events["day"].max())
    latest = survived[survived["day"] == survived["day"].max()] if not survived.empty \
        else events[events["event"] == "born"]

    st.subheader("Survival colony")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Day", last_day)
    c2.metric("Alive", len(alive_ids))
    c3.metric("Born", int((events["event"] == "born").sum()))
    c4.metric("Let go", int((events["event"] == "died").sum()),
              help="dismissed for missing the target (below the death line or kill switch)")
    c5.metric("Colony equity", f"{latest['equity'].sum():,.0f}")

    left, right = st.columns([1, 2])
    with left:
        st.caption("population and colony equity by day")
        if not survived.empty:
            by_day = survived.groupby("day").agg(alive=("agent_id", "count"),
                                                 equity=("equity", "sum"))
            st.line_chart(by_day["alive"], height=150)
            st.line_chart(by_day["equity"], height=150)
    with right:
        st.caption("lineage — who cloned whom, who was let go")
        st.graphviz_chart(lineage_dot(events), width="stretch")

    frames = events[events["event"] == "employee_of_week"]
    if not frames.empty:
        f = frames.iloc[-1]
        st.caption(f"🏆 employee of the week: **{f['agent_id']}** ({f['detail']})")
    notable = events[events["event"].isin(["born", "cloned", "died", "target_hit",
                                           "consulted", "party", "employee_of_week",
                                           "immune", "spared", "trained"])].copy()
    notable["event"] = notable["event"].replace({
        "died": "let go", "consulted": "asked a tip", "party": "happy hour",
        "employee_of_week": "employee of the week", "immune": "immunity earned",
        "spared": "spared by immunity", "trained": "weekly training"})
    with st.expander(f"event log ({len(notable)} events)"):
        st.dataframe(notable[["day", "agent_id", "event", "equity", "detail"]]
                     .sort_values("day", ascending=False),
                     width="stretch", hide_index=True, height=260)


def leaderboard(summary: pd.DataFrame) -> pd.DataFrame:
    def compound_return(sub: pd.DataFrame) -> float:
        return (sub["end_equity"] / sub["start_equity"]).prod() - 1

    rows = []
    for agent_id, sub in summary.groupby("agent_id"):
        wins, losses = sub["n_wins"].sum(), sub["n_losses"].sum()
        rows.append({
            "agent": agent_id,
            "episodes": len(sub),
            "return": compound_return(sub),
            "win_rate": wins / (wins + losses) if (wins + losses) else float("nan"),
            "trades": int(sub["n_trades"].sum()),
            "max_drawdown": sub["max_drawdown"].max(),
            "halted": bool(sub["halted"].any()),
        })
    board = pd.DataFrame(rows).sort_values("return", ascending=False)
    return board.reset_index(drop=True)


def run_controls(db_path: str) -> background.RunState | None:
    """Sidebar panel that starts a tournament in-process (what a hosted
    deploy needs, since there is no second terminal to run the CLI in)."""
    run = background.current_run()
    st.sidebar.subheader("Run")
    mode = st.sidebar.radio("Mode", ["Survival colony", "Tournament"], horizontal=True,
                            help="Survival: daily target, death below the line, clones paid "
                                 "from profit. Tournament: episodes with fresh wallets.")
    with st.sidebar.form("run_form"):
        if mode == "Survival colony":
            days = st.slider("Days", 5, 180, 60)
            budget = st.number_input("Budget per agent", 100.0, 100_000.0, 1_000.0, step=100.0)
            target = st.slider("Daily target %", 0.0, 3.0, 0.5, 0.1)
            death = st.slider("Dead below % of budget", 0, 95, 60, 5)
            cost = st.slider("Cost of living %/day", 0.0, 2.0, 0.1, 0.05)
            pressure = st.slider("Pressure after a miss", 0.0, 1.0, 0.0, 0.1,
                                 help="order size × (1+pressure) per consecutive missed "
                                      "target — the gambler's-ruin incentive, off by default")
            max_pop = st.slider("Max population", 5, 30, 12)
            episodes, steps = 0, 24
        else:
            episodes = st.slider("Episodes", 1, 10, 3)
            steps = 24 * st.slider("Days per episode (hourly bars)", 1, 30, 7)
            days = budget = target = death = cost = pressure = max_pop = 0
        endogenous = st.checkbox("Endogenous market (order book)", value=True)
        llm_ok = ClaudeTraderAgent.available()
        llm = st.checkbox("Include Claude trader", value=False, disabled=not llm_ok,
                          help=None if llm_ok else
                          "set ANTHROPIC_API_KEY (Streamlit secrets on the cloud)")
        seed_text = st.text_input("Seed (optional)", "")
        submitted = st.form_submit_button(
            "Start", disabled=run is not None and run.running, width="stretch")
    if submitted:
        seed = int(seed_text) if seed_text.strip().lstrip("-").isdigit() else None
        if mode == "Survival colony":
            config = RunConfig(db_path=db_path, mode="survival", days=days, budget=budget,
                               daily_target=target / 100, death_below=death / 100,
                               daily_cost=cost / 100, pressure=pressure,
                               max_population=max_pop, endogenous=endogenous,
                               llm=llm, seed=seed)
        else:
            config = RunConfig(db_path=db_path, episodes=episodes, steps=steps,
                               endogenous=endogenous, llm=llm, seed=seed)
        run = background.start_tournament(config)
        st.rerun()

    if run is not None and run.running:
        what = (f"{run.config.days} days of survival" if run.config.mode == "survival"
                else f"{run.config.episodes} episodes × {run.config.steps} bars")
        st.sidebar.info(f"running… {what}")
    elif run is not None and run.error:
        st.sidebar.error("last run failed")
        with st.sidebar.expander("traceback"):
            st.code(run.error)
    elif run is not None:
        st.sidebar.success(f"finished in {run.finished_at - run.started_at:.0f}s")

    if st.sidebar.button("Reset journal", disabled=run is not None and run.running,
                         width="stretch"):
        for suffix in ("", "-wal", "-shm"):
            Path(db_path + suffix).unlink(missing_ok=True)
        st.rerun()
    return run


def main() -> None:
    args = _parse_args()
    st.set_page_config(page_title="CryptoArena", page_icon="🏟️", layout="wide")
    st.title("🏟️ CryptoArena")
    st.caption(f"reading `{args.db}` — start a run from the sidebar, or feed it with "
               "`cryptoarena run` in another terminal")

    run = run_controls(args.db)
    st.sidebar.divider()
    auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True)
    st.sidebar.button("Refresh now")

    data = load_data(args.db) if os.path.exists(args.db) else {}
    equity = data.get("equity", pd.DataFrame())
    summary = data.get("summary", pd.DataFrame())
    trades = data.get("trades", pd.DataFrame())
    lessons = data.get("lessons", pd.DataFrame())
    survival = data.get("survival", pd.DataFrame())

    if summary.empty and equity.empty and survival.empty:
        st.info(
            "No data yet. Press **Start** in the sidebar, or point a run at the same file:\n\n"
            f"```\ncryptoarena survive --days 60 --db {args.db}\n```"
        )
    else:
        running = run is not None and run.running
        if running:
            total = run.config.days if run.config.mode == "survival" else run.config.episodes
            unit = "day" if run.config.mode == "survival" else "episode"
            done = int(summary["episode"].max()) if not summary.empty else 0
            st.progress(min(done / total, 1.0), text=f"{unit} {done}/{total} complete")
        world_tab, data_tab = st.tabs(["🏢 The floor", "📊 Data"])
        with world_tab:
            state = build_state(data, running=running)
            components.html(render_world(state), height=650)
            st.caption("hover or click an agent for its vitals · green energy, red stress, "
                       "blue focus · the chatter is composed live from each agent's real "
                       "state and never stored")
            if state["agents"]:
                vitals = pd.DataFrame(state["agents"])[
                    ["agent_id", "role", "alive", "generation", "mood", "activity", "energy",
                     "stress", "focus", "motivation", "ego", "equity", "day_return", "streak",
                     "misses", "parties", "awards", "immune_until", "spared", "lessons",
                     "mentor"]].replace(
                    {"mood": {"dead": "let go"}, "activity": {"dead": "—"}})
                with st.expander("vitals table"):
                    st.dataframe(vitals, width="stretch", hide_index=True)
        with data_tab:
            data_view(equity, summary, trades, lessons, survival)

    if auto_refresh:
        time.sleep(2 if run is not None and run.running else 5)
        st.rerun()


def data_view(equity: pd.DataFrame, summary: pd.DataFrame, trades: pd.DataFrame,
              lessons: pd.DataFrame, survival: pd.DataFrame) -> None:
    if not survival.empty:
        colony_view(survival)
    if not summary.empty:
        st.subheader("Leaderboard (cumulative across episodes)")
        board = leaderboard(summary)
        st.dataframe(
            board.style.format({
                "return": "{:+.1%}", "win_rate": "{:.0%}", "max_drawdown": "{:.0%}",
            }),
            width="stretch", hide_index=True,
        )

    if not equity.empty:
        st.subheader("Equity curves")
        equity = equity.sort_values(["agent_id", "episode", "step"]).copy()
        equity["t"] = equity.groupby("agent_id").cumcount()
        pivot = equity.pivot(index="t", columns="agent_id", values="equity")
        st.line_chart(pivot)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Recent trades")
        if not trades.empty:
            st.dataframe(
                trades[["agent_id", "episode", "symbol", "side", "price",
                        "pnl", "regime", "reason"]],
                width="stretch", height=380, hide_index=True,
            )
        else:
            st.caption("no trades yet")
    with col2:
        st.subheader("Lessons learned (by importance)")
        if not lessons.empty:
            st.dataframe(
                lessons[["agent_id", "episode", "regime", "importance", "lesson"]],
                width="stretch", height=380, hide_index=True,
            )
        else:
            st.caption("no lessons yet")


if __name__ == "__main__":
    main()
