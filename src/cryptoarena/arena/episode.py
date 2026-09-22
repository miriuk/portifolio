from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.base import MarketView, TradingAgent
from ..learning.memory import TradeJournal, TradeRecord
from ..market.exchange import Fill, Order, SimulatedExchange
from ..portfolio.risk import RiskManager


@dataclass
class EpisodeResult:
    episode: int
    equity_curves: dict[str, list[float]] = field(default_factory=dict)
    max_drawdown: dict[str, float] = field(default_factory=dict)
    halted: dict[str, bool] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)   # closes of the last bar


def _realized_pnl(agent: TradingAgent, fill: Fill) -> float | None:
    """P&L realised by this fill: closing a long (sell) or a short (buy)."""
    held = agent.wallet.positions.get(fill.symbol, 0.0)
    basis = agent.wallet.cost_basis.get(fill.symbol, 0.0)
    if fill.side == "sell":
        if held <= 0:
            return None                                   # opening or adding to a short
        return (fill.price - basis) * min(fill.quantity, held) - fill.fee
    if held < 0:
        return (basis - fill.price) * min(fill.quantity, -held) - fill.fee
    return None


def run_episode(
    episode: int,
    market,
    agents: list[TradingAgent],
    journal: TradeJournal,
    steps: int = 24 * 30,
    exchange: SimulatedExchange | None = None,
    verbose: bool = False,
    step_offset: int = 0,
    record_step_offset: int = 0,
    risk: dict[str, RiskManager] | None = None,
) -> EpisodeResult:
    """One episode: agents live through `steps` hourly candles.

    Each agent has its own risk manager; every fill is recorded to the
    journal with the market regime at the time, so reflection can attribute
    outcomes to conditions.

    `step_offset` makes the clock the agents see continue across episodes
    that are really consecutive days of one market (survival mode) — their
    cooldowns compare against it, so a clock that restarted at 0 every day
    would leave them stuck "cooling down" forever.

    `record_step_offset` shifts only the step written to the journal, for a
    caller that feeds one candle per call and wants the day's tape to read
    0..23 all the same. `risk` lets such a caller keep each agent's risk
    manager (peak equity, kill switch) alive between calls.
    """
    if exchange is None:
        exchange = market if hasattr(market, "execute") else SimulatedExchange()
    if risk is None:
        risk = {}
    for a in agents:
        risk.setdefault(a.agent_id, RiskManager())
    result = EpisodeResult(episode=episode)
    for a in agents:
        result.equity_curves[a.agent_id] = []
        result.max_drawdown[a.agent_id] = 0.0

    for step in range(steps):
        candles = market.next_candles()
        prices = {c.symbol: c.close for c in candles}
        latest = {c.symbol: c for c in candles}
        regimes = getattr(market, "_regime", {})
        journal.record_market(episode, record_step_offset + step, prices, regimes)
        sentiment = (market.sentiment_at(candles[0].timestamp)
                     if candles and hasattr(market, "sentiment_at") else None)

        for agent in agents:
            agent.observe(candles)
            rm = risk[agent.agent_id]
            view = MarketView(candles=latest, history=agent.history,
                              prices=prices, step=step_offset + step, sentiment=sentiment)

            equity = agent.wallet.equity(prices)
            result.equity_curves[agent.agent_id].append(equity)
            journal.record_equity(agent.agent_id, episode, record_step_offset + step, equity)
            if rm.peak_equity > 0:
                dd = 1 - equity / rm.peak_equity
                result.max_drawdown[agent.agent_id] = max(
                    result.max_drawdown[agent.agent_id], dd)
            if rm.check_drawdown(equity):
                # kill switch: liquidate everything, sit out the rest
                for symbol, qty in list(agent.wallet.positions.items()):
                    if symbol not in latest:
                        continue
                    flat = (Order(agent.agent_id, symbol, "sell", qty, reason="risk:kill_switch")
                            if qty > 0 else
                            Order(agent.agent_id, symbol, "buy", 0.0, reason="risk:kill_switch",
                                  base_qty=-qty))
                    fill = exchange.execute(flat, latest[symbol])
                    pnl = _realized_pnl(agent, fill)
                    agent.wallet.apply(fill)
                    journal.record_trade(TradeRecord(
                        agent.agent_id, episode, symbol, fill.side, fill.quantity,
                        fill.price, fill.fee, fill.timestamp, "risk:kill_switch",
                        regimes.get(symbol, ""), pnl))
                if verbose:
                    print(f"  [{agent.agent_id}] KILL SWITCH at step {step}, "
                          f"equity {equity:.2f}")
                continue
            if rm.halted:
                continue

            orders = rm.stop_loss_exits(agent.wallet, prices, agent.agent_id)
            orders += agent.decide(view)
            for order in orders:
                vetted = order if order.reason.startswith("risk:") else \
                    rm.vet(order, agent.wallet, prices)
                if vetted is None:
                    continue
                candle = latest.get(vetted.symbol)
                if candle is None:
                    continue
                fill = exchange.execute(vetted, candle)
                if fill is None:  # live guards may refuse an order
                    continue
                pnl = _realized_pnl(agent, fill)
                try:
                    agent.wallet.apply(fill)
                except ValueError:
                    continue  # stale sizing (e.g. two orders same step); skip
                journal.record_trade(TradeRecord(
                    agent.agent_id, episode, fill.symbol, fill.side,
                    fill.quantity, fill.price, fill.fee, fill.timestamp,
                    fill.reason, regimes.get(fill.symbol, ""), pnl))

    for agent in agents:
        result.halted[agent.agent_id] = risk[agent.agent_id].halted
    result.last_prices = dict(prices) if steps else {}
    return result
