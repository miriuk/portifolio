"""The desk: what the agents do together, which none of them sees alone.

Each agent has its own seatbelt (portfolio/risk.py): no more than 35% of
*its* equity in one symbol, a stop-loss, a kill switch. Nobody looks at
the colony as a whole, and on the stocks floor that showed on day 4: four
agents bought Nvidia within the same bar. Nine wallets, one bet.

Two roles sit above the agents:

- the **risk officer** (`DeskLimits`) sees every order before it fills and
  clips or refuses the ones that would push the colony past a share of its
  equity in one symbol (`symbol_cap`), or past a share invested overall
  (`gross_cap`). Closing a position is never refused. Every "no" is written
  to the journal (`vetoed`, `clipped`) so it shows on the desk feed.
- the **PM** (`PMBook`) keeps one portfolio of its own, the same capital
  as the founders together, built from the agents' votes: after every bar
  it holds the colony's net weight in each symbol (each agent's weight,
  weighted by its equity), drops symbols too few agents hold
  (`consensus`), and trades only when a weight drifts more than `band`
  from its target. Agent A selling what agent B buys nets out inside the
  book instead of paying fees twice. The book is a shadow: it does not
  move the agents' wallets, so the colony and the PM can be compared on
  the same bars — and the backtest decides which one the floor follows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..market.exchange import Order
from ..portfolio.wallet import Wallet

PM_ID = "pm"


@dataclass
class DeskLimits:
    symbol_cap: float = 0.0     # max share of colony equity in one symbol, all agents together (0 = off)
    gross_cap: float = 0.0      # max share of colony equity invested, all agents together (0 = off)

    @property
    def active(self) -> bool:
        return bool(self.symbol_cap or self.gross_cap)


def _exposure(agents, prices: dict[str, float]) -> tuple[float, dict[str, float], float]:
    """(colony equity, gross exposure per symbol, gross exposure in total)."""
    equity, per, gross = 0.0, {}, 0.0
    for a in agents:
        equity += a.wallet.equity(prices)
        for sym, qty in a.wallet.positions.items():
            value = abs(qty) * prices.get(sym, 0.0)
            per[sym] = per.get(sym, 0.0) + value
            gross += value
    return equity, per, gross


class PMBook:
    """One portfolio built from the agents' holdings (see the module doc)."""

    def __init__(self, capital: float, consensus: float = 0.0, band: float = 0.05,
                 daily_cost: float = 0.0, exchange=None):
        self.capital = capital
        # its own fills, so the shadow book never touches the agents' slippage draws
        self.exchange = exchange
        self.consensus = consensus
        self.band = band
        self.daily_cost = daily_cost
        self.wallet = Wallet(cash=capital)
        self.equity_per_day: list[float] = []
        self.fills: list[dict] = []          # the latest trades, newest last (bounded)
        self.targets: dict[str, float] = {}

    def votes(self, agents, prices: dict[str, float]) -> dict[str, float]:
        """Target weight per symbol: the agents' weights, weighted by their
        equity (the colony's net book), minus the symbols fewer than
        `consensus` of the agents hold."""
        total, value, holders = 0.0, {}, {}
        live = [a for a in agents if a.wallet.equity(prices) > 0]
        for a in live:
            total += a.wallet.equity(prices)
            for sym, qty in a.wallet.positions.items():
                if qty <= 0 or sym not in prices:
                    continue                               # the book is long-only
                value[sym] = value.get(sym, 0.0) + qty * prices[sym]
                holders[sym] = holders.get(sym, 0) + 1
        if total <= 0:
            return {}
        n = len(live)
        return {sym: v / total for sym, v in value.items()
                if not self.consensus or holders[sym] / n >= self.consensus - 1e-9}

    def rebalance(self, agents, latest: dict, prices: dict[str, float], exchange,
                  ts: int = 0) -> list[dict]:
        """Move the book towards the votes: sells first (they pay for the
        buys), each only when its weight is off by more than `band` — or
        when the desk no longer holds the symbol at all."""
        targets = self.votes(agents, prices)
        self.targets = targets
        equity = self.wallet.equity(prices)
        if equity <= 0:
            return []
        made = []
        held = {s: q * prices.get(s, 0.0) / equity for s, q in self.wallet.positions.items()}
        symbols = sorted(set(targets) | set(held))
        sells = [(s, held.get(s, 0.0) - targets.get(s, 0.0)) for s in symbols]
        for sym, excess in sells:
            qty = self.wallet.positions.get(sym, 0.0)
            if qty <= 0 or sym not in latest:
                continue
            if targets.get(sym, 0.0) <= 0:
                sell_qty = qty                                  # nobody holds it any more
            elif excess > self.band:
                sell_qty = min(qty, excess * equity / prices[sym])
            else:
                continue
            made.append(self._fill(Order(PM_ID, sym, "sell", sell_qty, "pm:rebalance"),
                                   latest[sym], exchange, ts))
        equity = self.wallet.equity(prices)
        for sym in symbols:
            gap = targets.get(sym, 0.0) - (self.wallet.positions.get(sym, 0.0)
                                           * prices.get(sym, 0.0) / equity if equity else 0.0)
            if gap <= self.band or sym not in latest:
                continue
            amount = min(gap * equity, self.wallet.cash * 0.995)
            if amount < equity * 0.001:
                continue
            made.append(self._fill(Order(PM_ID, sym, "buy", amount, "pm:rebalance"),
                                   latest[sym], exchange, ts))
        return [m for m in made if m]

    def _fill(self, order: Order, candle, exchange, ts: int) -> dict | None:
        fill = (self.exchange or exchange).execute(order, candle)
        if fill is None:
            return None
        try:
            self.wallet.apply(fill)
        except ValueError:
            return None
        rec = {"ts": int(ts or fill.timestamp), "symbol": fill.symbol, "side": fill.side,
               "quantity": fill.quantity, "price": fill.price, "fee": fill.fee}
        self.fills = (self.fills + [rec])[-50:]
        return rec

    def end_day(self, prices: dict[str, float]) -> float:
        """Rent is due here too (the same agents run it), then the day's mark."""
        self.wallet.cash -= self.capital * self.daily_cost
        eq = self.wallet.equity(prices)
        self.equity_per_day.append(eq)
        return eq

    # ------------------------------------------------------------ persistence
    def dump(self) -> dict:
        w = self.wallet
        return {"capital": self.capital, "consensus": self.consensus, "band": self.band,
                "daily_cost": self.daily_cost,
                "wallet": {"cash": w.cash, "positions": dict(w.positions),
                           "cost_basis": dict(w.cost_basis), "fees_paid": w.fees_paid},
                "equity_per_day": self.equity_per_day, "fills": self.fills,
                "targets": self.targets}

    @classmethod
    def load(cls, d: dict) -> "PMBook":
        book = cls(d["capital"], d.get("consensus", 0.0), d.get("band", 0.05),
                   d.get("daily_cost", 0.0))
        w = d.get("wallet") or {}
        book.wallet = Wallet(cash=w.get("cash", d["capital"]),
                             positions=dict(w.get("positions", {})),
                             cost_basis=dict(w.get("cost_basis", {})),
                             fees_paid=w.get("fees_paid", 0.0))
        book.equity_per_day = list(d.get("equity_per_day", []))
        book.fills = list(d.get("fills", []))
        book.targets = dict(d.get("targets", {}))
        return book


@dataclass
class Desk:
    """The roles above the agents for one colony. `day` is the colony day
    the journal entries are filed under; the caller keeps it current."""

    limits: DeskLimits = field(default_factory=DeskLimits)
    pm: PMBook | None = None
    journal: object = None
    day: int = 0
    vetoes: int = 0
    clipped: int = 0

    def vet(self, order: Order, agent, agents, prices: dict[str, float]) -> Order | None:
        """The risk officer's look at one order, after the agent's own risk
        manager: clip it to the room the colony has left, or refuse it.
        Anything that shrinks a position passes untouched."""
        if not self.limits.active or order.reason.startswith("risk:"):
            return order
        price = prices.get(order.symbol, 0.0)
        if price <= 0:
            return order
        held = agent.wallet.positions.get(order.symbol, 0.0)
        if order.side == "buy":
            if order.base_qty or held < 0:
                return order                                # covering a short
            value = order.quote_amount
        else:
            opening = order.quote_amount - max(held, 0.0)   # the part that goes short
            if opening <= 1e-12:
                return order
            value = opening * price
        equity, per, gross = _exposure(agents, prices)
        if equity <= 0:
            return order
        rooms = []
        if self.limits.symbol_cap:
            rooms.append((self.limits.symbol_cap * equity - per.get(order.symbol, 0.0),
                          f"{order.symbol} at {per.get(order.symbol, 0.0) / equity:.0%} of the desk "
                          f"(cap {self.limits.symbol_cap:.0%})"))
        if self.limits.gross_cap:
            rooms.append((self.limits.gross_cap * equity - gross,
                          f"desk {gross / equity:.0%} invested (cap {self.limits.gross_cap:.0%})"))
        room, why = min(rooms, key=lambda r: r[0])
        if room >= value:
            return order
        if room < max(equity * 0.001, value * 0.05):
            self.vetoes += 1
            self._note(agent.agent_id, "vetoed", value, f"{order.side} {order.symbol} refused: {why}")
            return None
        self.clipped += 1
        self._note(agent.agent_id, "clipped", room,
                   f"{order.side} {order.symbol} cut from {value:.2f} to {room:.2f}: {why}")
        if order.side == "buy":
            return Order(order.agent_id, order.symbol, "buy", room, order.reason)
        return Order(order.agent_id, order.symbol, "sell",
                     max(held, 0.0) + room / price, order.reason)

    def after_bar(self, agents, latest: dict, prices: dict[str, float], exchange,
                  ts: int = 0) -> None:
        if self.pm is not None:
            for rec in self.pm.rebalance(agents, latest, prices, exchange, ts):
                self._note(PM_ID, "pm_trade", rec["quantity"] * rec["price"],
                           f"{rec['side']} {rec['symbol']} {rec['quantity'] * rec['price']:.2f} "
                           f"at {rec['price']:.2f}")

    def _note(self, agent_id: str, event: str, value: float, detail: str) -> None:
        if self.journal is not None:
            self.journal.record_survival_event(self.day, agent_id, event, round(value, 4),
                                               detail=f"desk: {detail}")
