from pathlib import Path

import pytest

from cryptoarena.agents.rules import BreakoutAgent, MeanReversionAgent, MomentumAgent
from cryptoarena.arena.tournament import run_tournament
from cryptoarena.learning.memory import TradeJournal, TradeRecord
from cryptoarena.learning.reflection import EpisodeStats, compute_stats
from cryptoarena.market.candle import Candle
from cryptoarena.market.exchange import Order, SimulatedExchange
from cryptoarena.market.synthetic import SyntheticMarket
from cryptoarena.portfolio.risk import RiskLimits, RiskManager
from cryptoarena.portfolio.wallet import Wallet


def make_candle(price=100.0, volume=1000.0):
    return Candle("BTCUSDT", 1_700_000_000, price, price * 1.01, price * 0.99,
                  price, volume)


def test_synthetic_market_produces_candles():
    market = SyntheticMarket({"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0}, seed=1)
    candles = market.next_candles()
    assert {c.symbol for c in candles} == {"BTCUSDT", "ETHUSDT"}
    for c in candles:
        assert c.low <= c.open <= c.high
        assert c.low <= c.close <= c.high
        assert c.volume > 0


def test_exchange_charges_fees_and_slippage():
    ex = SimulatedExchange(fee_rate=0.001, seed=0)
    candle = make_candle(100.0)
    fill = ex.execute(Order("a", "BTCUSDT", "buy", 1000.0), candle)
    assert fill.price > 100.0          # buy slips up
    assert fill.fee == pytest.approx(1.0)
    sell = ex.execute(Order("a", "BTCUSDT", "sell", 5.0), candle)
    assert sell.price < 100.0          # sell slips down


def test_wallet_roundtrip():
    ex = SimulatedExchange(seed=0)
    wallet = Wallet(cash=10_000.0)
    candle = make_candle(100.0)
    buy = ex.execute(Order("a", "BTCUSDT", "buy", 1000.0), candle)
    wallet.apply(buy)
    assert wallet.cash == pytest.approx(9_000.0)
    assert wallet.positions["BTCUSDT"] > 0
    sell = ex.execute(Order("a", "BTCUSDT", "sell", wallet.positions["BTCUSDT"]), candle)
    wallet.apply(sell)
    assert "BTCUSDT" not in wallet.positions
    assert wallet.cash < 10_000.0  # fees + slippage cost money


def test_wallet_rejects_overspend():
    wallet = Wallet(cash=10.0)
    ex = SimulatedExchange(seed=0)
    fill = ex.execute(Order("a", "BTCUSDT", "buy", 1000.0), make_candle())
    with pytest.raises(ValueError):
        wallet.apply(fill)


def test_risk_manager_clips_and_stops():
    rm = RiskManager(RiskLimits(max_order_pct=0.1))
    wallet = Wallet(cash=10_000.0)
    prices = {"BTCUSDT": 100.0}
    vetted = rm.vet(Order("a", "BTCUSDT", "buy", 5_000.0), wallet, prices)
    assert vetted.quote_amount <= 1_000.0 + 1e-6
    wallet.positions["BTCUSDT"] = 10.0
    wallet.cost_basis["BTCUSDT"] = 200.0  # down 50% from basis
    stops = rm.stop_loss_exits(wallet, prices, "a")
    assert len(stops) == 1 and stops[0].reason == "risk:stop_loss"


def test_kill_switch():
    rm = RiskManager(RiskLimits(max_drawdown_pct=0.5))
    assert rm.check_drawdown(1000.0) is False
    assert rm.check_drawdown(499.0) is True
    assert rm.halted


def test_journal_persistence(tmp_path):
    db = tmp_path / "j.db"
    journal = TradeJournal(db)
    journal.record_trade(TradeRecord("a", 1, "BTCUSDT", "sell", 1.0, 100.0,
                                     0.1, 1, "x", "bull", 5.0))
    journal.add_lesson("a", 1, "don't overtrade")
    journal.save_params("a", {"lookback": 24}, 1)
    journal.close()
    journal2 = TradeJournal(db)
    assert len(journal2.trades_for("a")) == 1
    assert journal2.lessons_for("a") == ["don't overtrade"]
    assert journal2.load_params("a") == ({"lookback": 24}, 1)
    journal2.close()


def test_reflection_generates_lessons(tmp_path):
    journal = TradeJournal(tmp_path / "j.db")
    trades = [TradeRecord("a", 1, "BTCUSDT", "sell", 1.0, 90.0, 0.1, i,
                          "risk:stop_loss", "crash", -100.0) for i in range(3)]
    stats = compute_stats("a", 1, trades, 10_000.0, 9_000.0, max_drawdown=0.35)
    from cryptoarena.learning.reflection import reflect_on_episode
    lessons = reflect_on_episode(journal, stats)
    assert any("stop-losses" in l for l in lessons)
    assert any("drawdown" in l for l in lessons)
    assert any("crash" in l for l in lessons)
    assert journal.lessons_for("a")  # persisted
    journal.close()


def test_agent_learns_from_lessons():
    agent = MomentumAgent("m", 10_000.0)
    before = agent.params["entry_threshold"]
    agent.learn(["episode 1: hit 4 stop-losses — entries are too aggressive"])
    assert agent.params["entry_threshold"] > before


def test_full_tournament_smoke(tmp_path):
    journal = TradeJournal(tmp_path / "arena.db")
    agents = [MomentumAgent("m1", 10_000.0), MeanReversionAgent("mr1", 10_000.0),
              BreakoutAgent("b1", 10_000.0)]
    out = run_tournament(agents, journal, episodes=2, steps_per_episode=24 * 7,
                         seed=42, verbose=False)
    assert set(out["stats"]) == {"m1", "mr1", "b1"}
    for stats in out["stats"].values():
        assert len(stats) == 2
    journal.close()
