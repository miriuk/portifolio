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

from cryptoarena.agents.llm import ClaudeTraderAgent
from cryptoarena.arena import background
from cryptoarena.arena.background import RunConfig


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


def load_data(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        equity = _read_table(conn, "SELECT * FROM equity_snapshots")
        summary = _read_table(conn, "SELECT * FROM episode_summary")
        trades = _read_table(conn, "SELECT * FROM trades ORDER BY id DESC LIMIT 300")
        lessons = _read_table(
            conn, "SELECT * FROM lessons ORDER BY importance DESC, id DESC LIMIT 150")
    finally:
        conn.close()
    return equity, summary, trades, lessons


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
    st.sidebar.subheader("Run a tournament")
    with st.sidebar.form("run_form"):
        episodes = st.slider("Episodes", 1, 10, 3)
        days = st.slider("Days per episode (hourly bars)", 1, 30, 7)
        endogenous = st.checkbox("Endogenous market (order book)", value=True)
        llm_ok = ClaudeTraderAgent.available()
        llm = st.checkbox("Include Claude trader", value=False, disabled=not llm_ok,
                          help=None if llm_ok else
                          "set ANTHROPIC_API_KEY (Streamlit secrets on the cloud)")
        seed_text = st.text_input("Seed (optional)", "")
        submitted = st.form_submit_button(
            "Start", disabled=run is not None and run.running, use_container_width=True)
    if submitted:
        seed = int(seed_text) if seed_text.strip().lstrip("-").isdigit() else None
        run = background.start_tournament(RunConfig(
            db_path=db_path, episodes=episodes, steps=24 * days,
            endogenous=endogenous, llm=llm, seed=seed))
        st.rerun()

    if run is not None and run.running:
        st.sidebar.info(f"running… {run.config.episodes} episodes, "
                        f"{run.config.steps} bars each")
    elif run is not None and run.error:
        st.sidebar.error("last run failed")
        with st.sidebar.expander("traceback"):
            st.code(run.error)
    elif run is not None:
        st.sidebar.success(f"finished in {run.finished_at - run.started_at:.0f}s")

    if st.sidebar.button("Reset journal", disabled=run is not None and run.running,
                         use_container_width=True):
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

    equity, summary, trades, lessons = load_data(args.db) if os.path.exists(args.db) \
        else (pd.DataFrame(),) * 4

    if summary.empty and equity.empty:
        st.info(
            "No data yet. Press **Start** in the sidebar, or point a run at the same file:\n\n"
            f"```\ncryptoarena run --episodes 5 --db {args.db}\n```"
        )
    else:
        if run is not None and run.running:
            done = int(summary["episode"].max()) if not summary.empty else 0
            st.progress(done / run.config.episodes,
                        text=f"episode {done}/{run.config.episodes} complete")
        st.subheader("Leaderboard (cumulative across episodes)")
        board = leaderboard(summary)
        st.dataframe(
            board.style.format({
                "return": "{:+.1%}", "win_rate": "{:.0%}", "max_drawdown": "{:.0%}",
            }),
            use_container_width=True, hide_index=True,
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
                    use_container_width=True, height=380, hide_index=True,
                )
            else:
                st.caption("no trades yet")
        with col2:
            st.subheader("Lessons learned (by importance)")
            if not lessons.empty:
                st.dataframe(
                    lessons[["agent_id", "episode", "regime", "importance", "lesson"]],
                    use_container_width=True, height=380, hide_index=True,
                )
            else:
                st.caption("no lessons yet")

    if auto_refresh:
        time.sleep(2 if run is not None and run.running else 5)
        st.rerun()


if __name__ == "__main__":
    main()
