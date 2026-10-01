"""Mirror the stocks colony onto Trading 212's practice account.

After each trading day the colony's agents hold paper positions; the
mirror makes the practice account hold the same number of shares of the
same stocks, with real fills at Trading 212's prices. It is a
reconciliation, not a replay of orders: every run reads the account
(positions plus orders still pending) and sends only the difference, so
running it twice, or after a missed day, never doubles a trade.

- Only the floor's own symbols are touched; anything else in the account
  is left alone. The mirror assumes the practice account holds nothing
  else in those symbols.
- Sells go first (they free cash), never more than the account can sell.
- A symbol Trading 212 does not list (US-domiciled ETFs are not sold to
  UK accounts) stays on paper and is reported.
- If an order's fate is unknown (timeout, dropped connection), the run
  stops sending: the next one reads the account and carries on.
- T212_PAUSE=true stops it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .trading212 import OrderUncertain, PracticeAccount, T212Error


@dataclass
class Step:
    symbol: str
    action: str            # buy | sell | would_buy | would_sell | hold | missing | error | uncertain
    detail: dict = field(default_factory=dict)


def colony_holdings(state: dict) -> dict[str, float]:
    """Shares the living agents hold, summed, from the colony's saved state."""
    out: dict[str, float] = {}
    for ind in state.get("population", []):
        if ind.get("died_day") is not None:
            continue
        for sym, q in ((ind.get("agent") or {}).get("wallet") or {}).get("positions", {}).items():
            if q:
                out[sym] = out.get(sym, 0.0) + float(q)
    return out


def resolve(instruments: list[dict], symbol: str) -> str | None:
    """Trading 212's ticker for a US symbol: SYM_US_EQ, else a USD listing
    with that short name."""
    tickers = {i.get("ticker") for i in instruments}
    if f"{symbol}_US_EQ" in tickers:
        return f"{symbol}_US_EQ"
    for i in instruments:
        if i.get("shortName") == symbol and i.get("currencyCode") == "USD":
            return i.get("ticker")
    return None


def _pending(orders: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for o in orders:
        t = o.get("ticker") or (o.get("instrument") or {}).get("ticker")
        q = float(o.get("quantity") or 0.0)
        if o.get("side") == "SELL":
            q = -abs(q)
        elif o.get("side") == "BUY":
            q = abs(q)
        filled = float(o.get("filledQuantity") or 0.0)
        out[t] = out.get(t, 0.0) + q - math.copysign(filled, q) if q else out.get(t, 0.0)
    return out


def _trunc(x: float, decimals: int) -> float:
    f = 10 ** decimals
    return math.trunc(x * f) / f


def plan(target: dict[str, float], universe: list[str], instruments: list[dict],
         positions: list[dict], pending: list[dict], decimals: int = 2) -> tuple[list, list[Step]]:
    """(orders to send as (symbol, ticker, quantity), sells first; notes)."""
    held = {p.get("ticker") or (p.get("instrument") or {}).get("ticker"): p for p in positions}
    queued = _pending(pending)
    orders, notes = [], []
    for sym in universe:
        ticker = resolve(instruments, sym)
        want = target.get(sym, 0.0)
        if ticker is None:
            if want:
                notes.append(Step(sym, "missing", {"reason": "not listed at Trading 212: stays on paper",
                                                   "colony_shares": round(want, 4)}))
            continue
        pos = held.get(ticker) or {}
        have = float(pos.get("quantity") or 0.0) + queued.get(ticker, 0.0)
        qty = _trunc(want - have, decimals)
        if qty < 0:
            sellable = float(pos.get("quantityAvailableForTrading", pos.get("quantity", 0.0)) or 0.0)
            qty = -min(-qty, _trunc(sellable, decimals))
        if abs(qty) < 10 ** -decimals:
            notes.append(Step(sym, "hold", {"shares": round(have, 4)}))
            continue
        orders.append((sym, ticker, qty))
    orders.sort(key=lambda o: o[2] > 0)             # sells first, then buys in universe order
    return orders, notes


def mirror(account: PracticeAccount, target: dict[str, float], universe: list[str],
           execute: bool = False, paused: bool = False, decimals: int = 2) -> list[Step]:
    if paused:
        return [Step("-", "hold", {"reason": "paused (T212_PAUSE)"})]
    orders, notes = plan(target, universe, account.instruments(), account.positions(),
                         account.pending_orders(), decimals)
    steps = list(notes)
    for sym, ticker, qty in orders:
        side = "buy" if qty > 0 else "sell"
        if not execute:
            steps.append(Step(sym, f"would_{side}", {"ticker": ticker, "quantity": qty}))
            continue
        try:
            order = account.market_order(ticker, qty)
        except OrderUncertain as exc:
            steps.append(Step(sym, "uncertain", {"ticker": ticker, "quantity": qty, "error": str(exc)}))
            break                                   # read the account again before anything else
        except T212Error as exc:
            steps.append(Step(sym, "error", {"ticker": ticker, "quantity": qty, "error": str(exc)}))
            continue
        steps.append(Step(sym, side, {"ticker": ticker, "quantity": qty, "order": order.get("id"),
                                      "status": order.get("status")}))
    return steps


def report(steps: list[Step]) -> str:
    lines = ["Trading 212 practice account (virtual money):"]
    for s in steps:
        lines.append(f"  {s.symbol:<6} {s.action:<11} " + ", ".join(f"{k}={v}" for k, v in s.detail.items()))
    return "\n".join(lines)
