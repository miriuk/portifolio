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
- A symbol Trading 212 does not list, or lists but will not sell to this
  account, stays on paper and is reported. US-listed funds are the case:
  Trading 212 lists QQQ, but refuses the order (HTTP 400) to a UK
  account, which needs a UCITS version (PRIIPs); the mirror no longer
  tries them.
- If an order's fate is unknown (timeout, dropped connection), the run
  stops sending: the next one reads the account and carries on.
- T212_PAUSE=true stops it.

`summarize` keeps what the readiness scorecard (arena/readiness.py) needs
of a run — orders sent, orders in trouble, and how closely the account
followed the previous run's aim — as counts and ratios, never balances.
"""
from __future__ import annotations

import http.client
import math
import re
import urllib.error
from dataclasses import dataclass, field

from .trading212 import OrderUncertain, PracticeAccount, T212Error


class AccountUnreadable(RuntimeError):
    """The account could not be read: nothing was sent."""


@dataclass
class Step:
    symbol: str
    action: str            # buy | sell | would_buy | would_sell | hold | missing | error | uncertain | not_sent
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


# US-listed funds the floors hold: Trading 212 lists them, a UK account cannot buy them
US_FUNDS = {"SPY", "QQQ"}


def _us_fund(instrument: dict, symbol: str) -> bool:
    return symbol in US_FUNDS or (str(instrument.get("type", "")).upper() == "ETF"
                                  and str(instrument.get("ticker", "")).endswith("_US_EQ"))


def resolve(instruments: list[dict], symbol: str) -> str | None:
    """Trading 212's ticker for a US symbol: SYM_US_EQ, else a USD listing
    with that short name; None when it is not listed, or is a US-listed
    fund this (UK) account cannot buy. A UCITS fund on the London
    exchange, even quoted in dollars, resolves as usual."""
    by_ticker = {i.get("ticker"): i for i in instruments}
    inst = by_ticker.get(f"{symbol}_US_EQ") or next(
        (i for i in instruments if i.get("shortName") == symbol and i.get("currencyCode") == "USD"),
        None)
    if inst is None or _us_fund(inst, symbol):
        return None
    return inst.get("ticker")


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
    """(orders to send as (symbol, ticker, quantity, book), sells first; notes).
    `book` is {"want": the colony's shares, "have": the account's, pending
    orders included, "queued": the pending part}, kept on every step of a
    listed symbol."""
    held = {p.get("ticker") or (p.get("instrument") or {}).get("ticker"): p for p in positions}
    queued = _pending(pending)
    orders, notes = [], []
    for sym in universe:
        ticker = resolve(instruments, sym)
        want = target.get(sym, 0.0)
        if ticker is None:
            if want:
                notes.append(Step(sym, "missing", {
                    "reason": "not available to this account at Trading 212 (a US-listed fund "
                              "needs a UCITS version): stays on paper",
                    "colony_shares": round(want, 4)}))
            continue
        pos = held.get(ticker) or {}
        have = float(pos.get("quantity") or 0.0) + queued.get(ticker, 0.0)
        book = {"want": round(want, 6), "have": round(have, 6),
                "queued": round(queued.get(ticker, 0.0), 6)}
        qty = _trunc(want - have, decimals)
        if qty < 0:
            sellable = float(pos.get("quantityAvailableForTrading", pos.get("quantity", 0.0)) or 0.0)
            qty = -min(-qty, _trunc(sellable, decimals))
        if abs(qty) < 10 ** -decimals:
            notes.append(Step(sym, "hold", {"shares": round(have, 4), **book}))
            continue
        orders.append((sym, ticker, qty, book))
    orders.sort(key=lambda o: o[2] > 0)             # sells first, then buys in universe order
    return orders, notes


def mirror(account: PracticeAccount, target: dict[str, float], universe: list[str],
           execute: bool = False, paused: bool = False, decimals: int = 2) -> list[Step]:
    if paused:
        return [Step("-", "hold", {"reason": "paused (T212_PAUSE)"})]
    try:
        instruments, positions, pending = (account.instruments(), account.positions(),
                                           account.pending_orders())
    except (T212Error, urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError,
            ValueError) as exc:
        raise AccountUnreadable(str(exc)) from exc
    orders, notes = plan(target, universe, instruments, positions, pending, decimals)
    steps = list(notes)
    stopped = False
    for sym, ticker, qty, book in orders:
        side = "buy" if qty > 0 else "sell"
        if stopped:                                 # read the account again before anything else
            steps.append(Step(sym, "not_sent", {"ticker": ticker, "quantity": qty, **book,
                                                "reason": "an earlier order went unanswered"}))
            continue
        if not execute:
            steps.append(Step(sym, f"would_{side}", {"ticker": ticker, "quantity": qty, **book}))
            continue
        try:
            order = account.market_order(ticker, qty)
        except (OrderUncertain, ValueError) as exc:  # sent, but no answer that reads as one
            steps.append(Step(sym, "uncertain", {"ticker": ticker, "quantity": qty, **book,
                                                 "error": str(exc), "reason": _reason(exc)}))
            stopped = True
            continue
        except T212Error as exc:
            steps.append(Step(sym, "error", {"ticker": ticker, "quantity": qty, **book,
                                             "error": str(exc), "reason": _reason(exc)}))
            continue
        steps.append(Step(sym, side, {"ticker": ticker, "quantity": qty, **book,
                                      "order": order.get("id"), "status": order.get("status")}))
    return steps


def _reason(exc: Exception) -> str:
    """What went wrong, as the broker's error code: the HTTP status and the
    `code` field of its answer, never its free text (which could carry the
    account's numbers into the public log)."""
    status = getattr(exc, "status", None)
    code = re.search(r'"(?:code|errorCode|type)"\s*:\s*"([A-Za-z0-9_.-]{1,60})"', str(exc))
    parts = [f"HTTP {status}" if status else type(exc).__name__]
    if code:
        parts.append(code.group(1))
    return " ".join(parts)


def summarize(steps: list[Step], prices: dict[str, float], previous: dict[str, float] | None) -> dict:
    """What the readiness scorecard keeps of an executed run.

    - `orders`: orders sent; `problems`: orders that failed or went
      unanswered (a run with none is `ok`);
    - `tracking`: before this run sent anything, how far the account was
      from what the previous run aimed it at, as a share of that aim's
      value at today's prices. It catches what the run itself cannot see:
      an order rejected at the open, a partial fill, a hand in the account.
      None on the first run, and while an order still waits for the open
      (the 05:30 retry after the 01:30 run): it cannot be judged yet;
    - `unlisted`: the share of the colony's positions the broker does not
      list, which stays on paper;
    - `aim`: the shares this run aimed the account at, for tomorrow's
      `tracking` (the colony's own paper numbers, nothing of the account's);
    - `reasons`: per order in trouble, its symbol and the broker's error
      code (`_reason`), so a failed night can be read without the job log.
    """
    book = {s.symbol: s.detail for s in steps if "want" in s.detail}
    tracking = None
    waiting = any(d.get("queued") for d in book.values())
    if previous is not None and book and not waiting:
        base = sum(abs(previous.get(sym, 0.0)) * prices.get(sym, 0.0) for sym in book)
        gap = sum(abs(previous.get(sym, 0.0) - d["have"]) * prices.get(sym, 0.0)
                  for sym, d in book.items())
        tracking = gap / base if base > 0 else (0.0 if gap <= 0 else 1.0)
    listed = sum(d["want"] * prices.get(sym, 0.0) for sym, d in book.items())
    paper = sum(float(s.detail.get("colony_shares", 0.0)) * prices.get(s.symbol, 0.0)
                for s in steps if s.action == "missing")
    return {"orders": sum(1 for s in steps if s.action in ("buy", "sell")),
            "problems": sum(1 for s in steps if s.action in ("error", "uncertain")),
            "missed": 0,
            "tracking": None if tracking is None else round(tracking, 6),
            "unlisted": round(paper / (listed + paper), 6) if listed + paper > 0 else 0.0,
            "aim": {sym: d["want"] for sym, d in book.items()},
            "reasons": [f"{s.symbol} {s.action}: {s.detail.get('reason', '')}".strip()
                        for s in steps if s.action in ("error", "uncertain")]}


def report(steps: list[Step]) -> str:
    lines = ["Trading 212 practice account (virtual money):"]
    for s in steps:
        lines.append(f"  {s.symbol:<6} {s.action:<11} " + ", ".join(f"{k}={v}" for k, v in s.detail.items()))
    return "\n".join(lines)
