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


def _realized_pnl(agent: TradingAgent, fill: Fill) -> float | None:
    if fill.side != "sell":
        return None
    basis = agent.wallet.cost_basis.get(fill.symbol, 0.0)
    return (fill.price - basis) * fill.quantity - fill.fee


def run_episode(
    episode: int,
    market,
    agents: list[TradingAgent],
    journal: TradeJournal,
    steps: int = 24 * 30,
    exchange: SimulatedExchange | None = None,
    verbose: bool = False,
) -> EpisodeResult:
    """One episode: agents live through `steps` hourly candles.

    Each agent has its own risk manager; every fill is recorded to the
    journal with the market regime at the time, so reflection can attribute
    outcomes to conditions.
    """
    if exchange is None:
        exchange = market if hasattr(market, "execute") else SimulatedExchange()
    risk = {a.agent_id: RiskManager() for a in agents}
    result = EpisodeResult(episode=episode)
    for a in agents:
        result.equity_curves[a.agent_id] = []
        result.max_drawdown[a.agent_id] = 0.0

    for step in range(steps):
        candles = market.next_candles()
        prices = {c.symbol: c.close for c in candles}
        latest = {c.symbol: c for c in candles}
        regimes = getattr(market, "_regime", {})

        for agent in agents:
            agent.observe(candles)
            rm = risk[agent.agent_id]
            view = MarketView(candles=latest, history=agent.history,
                              prices=prices, step=step)

            equity = agent.wallet.equity(prices)
            result.equity_curves[agent.agent_id].append(equity)
            journal.record_equity(agent.agent_id, episode, step, equity)
            if rm.peak_equity > 0:
                dd = 1 - equity / rm.peak_equity
                result.max_drawdown[agent.agent_id] = max(
                    result.max_drawdown[agent.agent_id], dd)
            if rm.check_drawdown(equity):
                # kill switch: liquidate everything, sit out the rest
                for symbol, qty in list(agent.wallet.positions.items()):
                    fill = exchange.execute(
                        Order(agent.agent_id, symbol, "sell", qty,
                              reason="risk:kill_switch"),
                        latest[symbol])
                    pnl = _realized_pnl(agent, fill)
                    agent.wallet.apply(fill)
                    journal.record_trade(TradeRecord(
                        agent.agent_id, episode, symbol, "sell", fill.quantity,
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
    return result
