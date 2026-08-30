"""Live web dashboard for CryptoArena — watch a run as it happens.

Run with:
    cryptoarena dashboard              # launches this via streamlit for you
    streamlit run src/cryptoarena/dashboard.py -- --db arena.db

It only *reads* the journal (WAL mode lets it do that safely while a
`cryptoarena run` in another terminal is writing to the same file), so it
never interferes with the tournament itself.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import pandas as pd
import streamlit as st


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


def main() -> None:
    args = _parse_args()
    st.set_page_config(page_title="CryptoArena", page_icon="🏟️", layout="wide")
    st.title("🏟️ CryptoArena")
    st.caption(f"reading `{args.db}` — run `cryptoarena run` in another terminal to feed it")

    auto_refresh = st.sidebar.checkbox("Auto-refresh every 5s", value=True)
    st.sidebar.button("Refresh now")

    equity, summary, trades, lessons = load_data(args.db)

    if summary.empty and equity.empty:
        st.info(
            "No data yet in this database. Start a run pointed at the same file, e.g.:\n\n"
            f"```\ncryptoarena run --episodes 5 --db {args.db}\n```"
        )
    else:
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
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
