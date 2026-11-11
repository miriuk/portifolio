"""The Crypto Fear & Greed index: on the backtest tape, in the live colony,
and as the rule agents' greed gate."""
import csv

from cryptoarena.agents.base import MarketView
from cryptoarena.agents.rules import MomentumAgent
from cryptoarena.arena.backtest import TapeSlice, load_sentiment, load_tape
from cryptoarena.market.candle import Candle


def write_fng(directory, rows):
    (directory / "sentiment").mkdir()
    with (directory / "sentiment" / "fng.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "value", "label"])
        w.writerows(rows)


def test_sentiment_loads_by_day_and_tolerates_a_gap(tmp_path):
    from tests.test_backtest import write_tape
    write_tape(tmp_path, bars=48)
    day0 = 1_760_000_000 // 86400
    write_fng(tmp_path, [(day0 * 86400, 20, "Extreme Fear"), ((day0 + 2) * 86400, 80, "Greed")])
    fng = load_sentiment(tmp_path)
    assert fng == {day0: 20, day0 + 2: 80}
    assert load_sentiment(tmp_path / "nowhere") == {}
    slice_ = TapeSlice(load_tape(tmp_path), 0, 48, fng)
    assert slice_.sentiment_at(day0 * 86400 + 3600) == 20
    assert slice_.sentiment_at((day0 + 1) * 86400 + 3600) == 20     # yesterday's reading
    assert slice_.sentiment_at((day0 + 2) * 86400) == 80
    assert slice_.sentiment_at((day0 - 1) * 86400) is None


def _view(agent, sentiment):
    for i in range(30):
        p = 100 + 2 * i
        agent.observe([Candle("BTCUSD", i * 3600, p, p, p, p, 1e6)])
    return MarketView(candles={"BTCUSD": agent.history["BTCUSD"][-1]}, history=agent.history,
                      prices={"BTCUSD": 158.0}, step=30, sentiment=sentiment)


def test_the_greed_gate_vetoes_new_buys_while_the_crowd_is_greedy():
    fast = {"lookback": 12, "entry_threshold": 0.01, "trend_filter": 24, "market_gate": 24,
            "cooldown": 1, "rank_top": 0}
    hungry = MomentumAgent("m", 5.0, params={**fast, "greed_gate": 0})
    assert any(o.side == "buy" for o in hungry.decide(_view(hungry, 90)))   # gate off
    gated = MomentumAgent("g", 5.0, params={**fast, "greed_gate": 60})
    assert gated.decide(_view(gated, 78)) == []                             # greedy: no buys
    fearful = MomentumAgent("f", 5.0, params={**fast, "greed_gate": 60})
    assert any(o.side == "buy" for o in fearful.decide(_view(fearful, 30)))  # fearful: buys
    unknown = MomentumAgent("u", 5.0, params={**fast, "greed_gate": 60})
    assert any(o.side == "buy" for o in unknown.decide(_view(unknown, None)))  # no reading: no veto


def test_the_live_colony_remembers_the_day_reading(tmp_path):
    from cryptoarena.arena.live_colony import LiveColony
    from cryptoarena.learning.memory import TradeJournal
    from cryptoarena.market.live import LiveFeed, default_symbols
    from tests.test_live_colony import HOUR, T0, FakeClient, cfg
    client = FakeClient()
    client.now = T0 + 800 * HOUR
    reading = [72]
    feed = LiveFeed("kraken", default_symbols("kraken"), client=client,
                    now=lambda: client.now, sentiment=lambda: reading[0])
    journal = TradeJournal(tmp_path / "s.db")
    colony = LiveColony.open(journal, [MomentumAgent("momentum-1", 5.0)], cfg(), feed,
                             warmup=700, verbose=False)
    assert colony.sentiment is None                     # the founding bar had no reading yet
    colony.run_once()
    assert colony.sentiment == 72 and colony.status()["sentiment"] == 72
    reading[0] = None                                   # the site is down: keep the last value
    client.now += HOUR
    colony.run_once()
    assert colony.sentiment == 72
    journal.close()
    again = LiveColony.open(TradeJournal(tmp_path / "s.db"), [], cfg(), feed, verbose=False)
    assert again.sentiment == 72
    plain = LiveFeed("kraken", default_symbols("kraken"), client=client, now=lambda: client.now)
    assert plain.sentiment() is None                    # an injected client never hits the network
