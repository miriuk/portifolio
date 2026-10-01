"""The desk feed: one line per thing that happened, newest first, the way a
trading floor's chat scrolls — who bought what, what the risk officer
refused, what the PM moved, who was hired or let go, and the chief of
staff's note at the close of each day. Built from the journal only, so it
reads the same for a simulation and for the live colony.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd

# how each journal event shows on the feed: (tag, tone)
EVENTS = {
    "vetoed": ("RISK", "red"), "clipped": ("RISK", "amber"),
    "pm_trade": ("PM", "gold"), "pm_opened": ("PM", "gold"),
    "chief_note": ("CHIEF", "green"),
    "born": ("HR", "plain"), "cloned": ("HR", "plain"), "died": ("HR", "red"),
    "retired": ("HR", "plain"), "consulted": ("MENTOR", "plain"), "trained": ("MENTOR", "plain"),
    "senior": ("AWARD", "gold"), "employee_of_week": ("AWARD", "gold"), "party": ("AWARD", "plain"),
    "spared": ("HR", "plain"),
}
# within a day: trades, then the desk, then people, the chief last
ORDER = {"trade": 0, "RISK": 1, "PM": 2, "HR": 3, "MENTOR": 3, "AWARD": 4, "CHIEF": 5}
TONES = {"red": "#ff6b6b", "amber": "#f0b44c", "gold": "#e8c170", "green": "#7ed6a5",
         "plain": "#d8d4c8", "buy": "#7ed6a5", "sell": "#ff8f8f"}


def build_feed(trades: pd.DataFrame, events: pd.DataFrame, limit: int = 60) -> list[dict]:
    """Feed rows, newest first: {day, when, tag, text, tone}. `trades` and
    `events` are the journal's tables as the dashboard loads them."""
    rows: list[dict] = []
    if trades is not None and not trades.empty:
        for t in trades.itertuples():
            when = datetime.fromtimestamp(int(t.timestamp), tz=timezone.utc)
            value = float(t.quantity) * float(t.price)
            reason = f" · {t.reason}" if getattr(t, "reason", "") else ""
            rows.append({"day": int(t.episode), "ts": int(t.timestamp), "rank": ORDER["trade"],
                         "when": when.strftime("%d %b %H:%M"),
                         "tag": str(t.agent_id).upper(),
                         "text": f"{t.side} {t.symbol} {value:,.2f}{reason}",
                         "tone": "buy" if t.side == "buy" else "sell"})
    if events is not None and not events.empty:
        for e in events.itertuples():
            if e.event not in EVENTS:
                continue
            tag, tone = EVENTS[e.event]
            detail = str(e.detail or "").removeprefix("desk: ")
            text = {"born": f"{e.agent_id} joins" + (f" ({detail})" if detail else ""),
                    "died": f"{e.agent_id} let go ({detail})",
                    "retired": f"{e.agent_id} retired ({detail})",
                    "cloned": f"{e.agent_id} hires {detail}",
                    "senior": f"{e.agent_id} is the senior ({detail})",
                    "employee_of_week": f"{e.agent_id} employee of the week ({detail})",
                    "party": f"{e.agent_id} at the happy hour ({detail})",
                    }.get(e.event, f"{e.agent_id} · {detail}" if tag in ("RISK", "MENTOR", "HR")
                          else detail)
            rows.append({"day": int(e.day), "ts": None, "rank": ORDER[tag],
                         "when": f"day {int(e.day)}", "tag": tag, "text": text, "tone": tone})
    rows.sort(key=lambda r: (r["day"], r["rank"], r["ts"] or 0), reverse=True)
    return rows[:limit]


def render_feed(rows: list[dict], height: int = 420) -> str:
    """The feed as a dark terminal block (HTML, everything escaped)."""
    if not rows:
        return "<div style='color:#888;font-family:monospace'>nothing on the feed yet</div>"
    lines = []
    for r in rows:
        color = TONES.get(r["tone"], TONES["plain"])
        lines.append(
            "<div style='display:flex;gap:14px;padding:5px 0;border-bottom:1px solid #2a2a2a'>"
            f"<span style='color:#8a8a8a;min-width:92px'>{html.escape(r['when'])}</span>"
            f"<span style='color:{color};font-weight:700;min-width:110px'>"
            f"{html.escape(r['tag'])}</span>"
            f"<span style='color:#e9e6dc'>{html.escape(r['text'])}</span></div>")
    return ("<div style='background:#141414;border-radius:6px;padding:10px 16px;"
            f"font-family:ui-monospace,Menlo,monospace;font-size:13px;max-height:{height}px;"
            "overflow-y:auto'>" + "".join(lines) + "</div>")
