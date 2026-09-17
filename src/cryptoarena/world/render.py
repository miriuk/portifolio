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
        notable = survival[survival["event"].isin(
            ["born", "died", "cloned", "spared", "trained"])].tail(8)
        events = [{"day": int(r["day"]), "agent_id": r["agent_id"], "event": r["event"],
                   "detail": str(r["detail"] or ""),
                   "other": (r["parent_id"] if isinstance(r["parent_id"], str) else None)}
                  for _, r in notable.iterrows()]
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
        "party": party_state(survival, day),
        "senior": senior_state(survival),
    }


def senior_state(survival: pd.DataFrame) -> dict | None:
    if survival.empty:
        return None
    picks = survival[survival["event"] == "senior"]
    if picks.empty:
        return None
    last = picks.iloc[-1]
    return {"agent_id": str(last["agent_id"]), "ret": float(last["equity"]),
            "day": int(last["day"])}


def party_state(survival: pd.DataFrame, day: int) -> dict:
    """The latest happy hour: who is celebrated, who got the frame, and
    whether the party is happening right now (it lasts the evening of the
    day it was thrown)."""
    if survival.empty:
        return {"active": False, "winners": [], "employee": None, "week": 0, "day": 0}
    parties = survival[survival["event"] == "party"]
    frames = survival[survival["event"] == "employee_of_week"]
    if parties.empty:
        return {"active": False, "winners": [], "employee": None, "week": 0, "day": 0}
    last = int(parties["day"].max())
    winners = parties[parties["day"] == last]
    detail = str(winners.iloc[0]["detail"])
    week = int(detail.split(":")[0].replace("week", "").strip() or 0)
    return {
        "active": last == day,
        "day": last, "week": week,
        "winners": [{"agent_id": r["agent_id"], "ret": float(r["equity"])}
                    for _, r in winners.iterrows()],
        "employee": (str(frames.iloc[-1]["agent_id"]) if not frames.empty else None),
    }


def render_world(state: dict) -> str:
    html = _TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(state).replace("</", "<\\/")
    return html.replace("/*__STATE__*/null", payload)
