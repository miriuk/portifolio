import pytest

from cryptoarena.agents.rules import MeanReversionAgent, MomentumAgent
from cryptoarena.arena.tournament import run_tournament
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.market.endogenous import EndogenousMarket
from cryptoarena.market.exchange import Order
from cryptoarena.market.orderbook import BookLevel, OrderBook


def test_orderbook_partial_fill_and_depth():
    book = OrderBook()
    book.set_liquidity(
        asks=[BookLevel(101.0, 1.0), BookLevel(102.0, 1.0)],
        bids=[BookLevel(99.0, 1.0)],
    )
    assert book.best_ask == 101.0 and book.best_bid == 99.0
    fills = book.take("buy", 1.5)
    assert len(fills) == 2
    assert fills[0].price == 101.0 and fills[0].quantity == 1.0
    assert fills[1].price == 102.0 and fills[1].quantity == pytest.approx(0.5)
    assert book.depth("buy") == pytest.approx(0.5)  # half a unit left on asks


def test_orderbook_worse_price_for_size():
    book = OrderBook()
    book.set_liquidity(
        asks=[BookLevel(100.0 + i, 1.0) for i in range(10)], bids=[])
    small = book.take("buy", 0.5)
    small_vwap = sum(f.price * f.quantity for f in small) / 0.5
    book.set_liquidity(asks=[BookLevel(100.0 + i, 1.0) for i in range(10)], bids=[])
    big = book.take("buy", 5.0)
    big_vwap = sum(f.price * f.quantity for f in big) / 5.0
    assert big_vwap > small_vwap


def test_agent_flow_moves_the_market():
    market = EndogenousMarket({"BTCUSDT": 100.0}, seed=3, liquidity_scale=5_000.0)
    candles = market.next_candles()
    candle = candles[0]
    # a large buy eats the asks...
    fill = market.execute(Order("whale", "BTCUSDT", "buy", 4_000.0), candle)
    assert fill.price > candle.close  # paid above pre-trade price
    # ...and the next agent in the same step gets an even worse price
    fill2 = market.execute(Order("late", "BTCUSDT", "buy", 500.0), candle)
    assert fill2.price > fill.price
    # and the next candle opens where the flow pushed the price
    nxt = market.next_candles()[0]
    assert nxt.open > candle.close


def test_endogenous_fees_charged():
    market = EndogenousMarket({"BTCUSDT": 100.0}, seed=1)
    candle = market.next_candles()[0]
    fill = market.execute(Order("a", "BTCUSDT", "buy", 1000.0), candle)
    assert fill.fee == pytest.approx(1.0, rel=0.05)
    sell = market.execute(Order("a", "BTCUSDT", "sell", fill.quantity), candle)
    assert sell.fee > 0


def test_endogenous_tournament_smoke(tmp_path):
    journal = TradeJournal(tmp_path / "arena.db")
    agents = [MomentumAgent("m1", 10_000.0), MeanReversionAgent("mr1", 10_000.0)]
    out = run_tournament(agents, journal, episodes=2, steps_per_episode=24 * 5,
                         seed=11, verbose=False, endogenous=True)
    assert all(len(s) == 2 for s in out["stats"].values())
    journal.close()
