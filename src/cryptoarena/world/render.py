"""Turn journal frames into the JSON the isometric world consumes, and
inject it into the self-contained HTML/JS renderer."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .needs import compute_vitals

_TEMPLATE = Path(__file__).with_name("world.html")


def market_state(market: pd.DataFrame) -> dict:
    """Latest close per symbol, change over the last 24 bars, current regime."""
    if market.empty:
        return {"symbols": [], "regime": ""}
    latest = market.sort_values(["episode", "step"]).groupby("symbol").tail(25)
    symbols = []
    for sym, rows in latest.groupby("symbol"):
        rows = rows.sort_values(["episode", "step"])
        first, last = float(rows.iloc[0]["close"]), float(rows.iloc[-1]["close"])
        symbols.append({
            "symbol": sym, "close": round(last, 2),
            "change": round(last / first - 1, 4) if first > 0 else 0.0,
            "regime": str(rows.iloc[-1]["regime"] or ""),
        })
    regimes = [s["regime"] for s in symbols if s["regime"]]
    return {"symbols": symbols,
            "regime": max(set(regimes), key=regimes.count) if regimes else ""}


def build_state(data: dict[str, pd.DataFrame], running: bool = False) -> dict:
    empty = pd.DataFrame()
    summary = data.get("summary", empty)
    survival = data.get("survival", empty)
    vitals = compute_vitals(summary, data.get("trades", empty), data.get("lessons", empty),
                            survival)
    events = []
    if not survival.empty:
        notable = survival[survival["event"].isin(["born", "died", "cloned"])].tail(8)
        events = [{"day": int(r["day"]), "agent_id": r["agent_id"], "event": r["event"],
                   "detail": str(r["detail"] or "")} for _, r in notable.iterrows()]
    day = int(summary["episode"].max()) if not summary.empty else 0
    alive = [v for v in vitals if v.alive]
    return {
        "day": day,
        "running": running,
        "mode": "survival" if not survival.empty else "tournament",
        "colony": {"alive": len(alive), "total": len(vitals),
                   "equity": round(sum(v.equity for v in alive), 2)},
        "market": market_state(data.get("market", empty)),
        "agents": [v.to_dict() for v in vitals],
        "events": events,
    }


def render_world(state: dict) -> str:
    html = _TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(state).replace("</", "<\\/")
    return html.replace("/*__STATE__*/null", payload)
