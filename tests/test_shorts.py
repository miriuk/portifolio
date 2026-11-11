"""Paper shorts: the wallet goes negative, the risk manager caps the short
side, covers are never gated, and the bear pays its daily funding."""
from cryptoarena.agents.base import MarketView
from cryptoarena.agents.rules import BearAgent, MomentumAgent
from cryptoarena.market.candle import Candle
from cryptoarena.market.exchange import Fill, Order, SimulatedExchange
from cryptoarena.portfolio.risk import RiskManager
from cryptoarena.portfolio.wallet import Wallet


def fill(symbol, side, qty, price, fee=0.0):
    return Fill("a", symbol, side, qty, price, fee, 0)


def test_wallet_short_then_cover_realises_the_drop():
    w = Wallet(cash=100.0, allow_short=True)
    w.apply(fill("X", "sell", 2.0, 10.0, fee=0.05))          # short 2 @ 10
    assert w.positions["X"] == -2.0 and w.cost_basis["X"] == 10.0
    assert abs(w.cash - 119.95) < 1e-9
    assert abs(w.equity({"X": 8.0}) - (119.95 - 16.0)) < 1e-9   # the drop is a gain
    assert abs(w.short_notional({"X": 8.0}) - 16.0) < 1e-9
    assert abs(w.exposure({"X": 8.0}) - 16.0 / (119.95 - 16.0)) < 1e-9
    w.apply(fill("X", "buy", 2.0, 8.0, fee=0.04))            # cover
    assert "X" not in w.positions and "X" not in w.cost_basis
    assert abs(w.cash - (119.95 - 16.04)) < 1e-9


def test_a_long_only_wallet_still_refuses_to_oversell():
    w = Wallet(cash=10.0)
    try:
        w.apply(fill("X", "sell", 1.0, 5.0))
    except ValueError:
        return
    raise AssertionError("sold what it did not hold")


def test_risk_manager_caps_a_short_and_lets_a_cover_through():
    rm = RiskManager()
    w = Wallet(cash=10.0, allow_short=True)
    prices = {"X": 2.0}
    vetted = rm.vet(Order("a", "X", "sell", 100.0), w, prices)   # wants to short 100 units
    assert vetted is not None and vetted.quantity_value(prices) <= 10.0 * 0.25 + 1e-9 \
        if hasattr(vetted, "quantity_value") else vetted.quote_amount * 2.0 <= 2.5 + 1e-9
    w.apply(fill("X", "sell", 1.0, 2.0))
    cover = rm.vet(Order("a", "X", "buy", 0.0, base_qty=5.0), w, prices)
    assert cover is not None and cover.base_qty == 1.0        # never more than the short
    assert rm.vet(Order("a", "X", "buy", 0.0, base_qty=1.0), Wallet(cash=10.0), prices) is None
    # a short that ran against us is stopped out by the seatbelt
    assert rm.stop_loss_exits(w, {"X": 2.0 * 1.13}, "a")[0].side == "buy"


def test_exchange_fills_a_cover_for_the_exact_quantity():
    ex = SimulatedExchange(fee_rate=0.001, slippage_base=0.0, seed=1)
    c = Candle("X", 0, 10, 10, 10, 10, 1e9)
    f = ex.execute(Order("a", "X", "buy", 0.0, base_qty=3.0), c)
    assert f.quantity == 3.0 and abs(f.fee - 3.0 * f.price * 0.001) < 1e-12


def _tape(agent, n, path):
    for i in range(n):
        p_btc, p_alt = path(i)
        agent.observe([Candle("BTCUSD", i * 3600, p_btc, p_btc, p_btc, p_btc, 1e6),
                       Candle("ALTUSD", i * 3600, p_alt, p_alt, p_alt, p_alt, 1e6)])


def test_bear_shorts_the_weak_coin_in_a_falling_market_and_covers_the_bounce():
    bear = BearAgent("bear-1", 5.0, params={"market_gate": 48, "trend_filter": 48,
                                            "lookback": 24, "cooldown": 1})
    _tape(bear, 60, lambda i: (100 - i, 50 - 0.5 * i))       # everything sinks
    view = MarketView(candles={"BTCUSD": bear.history["BTCUSD"][-1],
                               "ALTUSD": bear.history["ALTUSD"][-1]},
                      history=bear.history, prices={"BTCUSD": 41.0, "ALTUSD": 20.5}, step=60)
    orders = bear.decide(view)
    assert orders and all(o.side == "sell" for o in orders)
    assert {o.symbol for o in orders} <= {"BTCUSD", "ALTUSD"}
    assert all(o.reason.startswith("short") for o in orders)
    # take the short, then a bounce: the cover is a buy with the exact quantity
    bear.wallet.apply(fill("ALTUSD", "sell", 0.07, 20.5))
    _tape(bear, 30, lambda i: (41.0, 20.5 + 0.2 * i))
    view = MarketView(candles={"BTCUSD": bear.history["BTCUSD"][-1],
                               "ALTUSD": bear.history["ALTUSD"][-1]},
                      history=bear.history, prices={"BTCUSD": 41.0, "ALTUSD": 26.3}, step=90)
    covers = [o for o in bear.decide(view) if o.side == "buy"]
    assert covers and covers[0].base_qty == 0.07 and covers[0].symbol == "ALTUSD"


def test_a_bull_never_shorts_and_the_bear_never_buys_into_a_rising_market():
    bull = MomentumAgent("m", 5.0)
    assert not bull.allow_short and not bull.wallet.allow_short
    bear = BearAgent("b", 5.0, params={"market_gate": 24, "lookback": 12, "cooldown": 1})
    _tape(bear, 40, lambda i: (100 + i, 50 + i))
    view = MarketView(candles={"BTCUSD": bear.history["BTCUSD"][-1],
                               "ALTUSD": bear.history["ALTUSD"][-1]},
                      history=bear.history, prices={"BTCUSD": 139.0, "ALTUSD": 89.0}, step=40)
    assert bear.decide(view) == []


def test_a_short_pays_its_funding_at_the_end_of_the_day(tmp_path):
    from cryptoarena.arena.episode import EpisodeResult
    from cryptoarena.arena.survival import (Individual, SurvivalConfig, SurvivalResult,
                                            _end_of_day, _next_id_factory)
    from cryptoarena.learning.memory import TradeJournal
    import numpy as np
    bear = BearAgent("bear-1", 5.0)
    bear.wallet.apply(fill("X", "sell", 1.0, 2.0))            # short 1 unit @ 2: notional 2
    ind = Individual(bear, "bear", 5.0, None, 0, born_day=0)
    cfg = SurvivalConfig(budget=5.0, daily_cost=0.0, short_funding=0.01, learn=False, seed=1)
    ep = EpisodeResult(episode=1, last_prices={"X": 2.0})
    ep.equity_curves["bear-1"] = [7.0 - 2.0, 7.0 - 2.0]
    ep.max_drawdown["bear-1"] = 0.0
    ep.halted["bear-1"] = False
    journal = TradeJournal(tmp_path / "j.db")
    cash_before = bear.wallet.cash
    _end_of_day(1, [ind], ep, cfg, np.random.default_rng(1), journal, _next_id_factory([bear]),
                SurvivalResult(), verbose=False)
    assert abs((cash_before - bear.wallet.cash) - 2.0 * 0.01) < 1e-9
    journal.close()
