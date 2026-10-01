"""Sources: a post becomes calls, calls are judged after their horizon,
and a source's trust is nothing but that record."""
import json
import sys

import pytest

from cryptoarena import cli
from cryptoarena.agents.base import MarketView
from cryptoarena.agents.rules import MomentumAgent
from cryptoarena.arena.live_colony import LiveColony
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.market.candle import Candle
from cryptoarena.market.live import LiveFeed, default_symbols
from cryptoarena.market.sources import Call, Post, Source, parse_calls, signals, trust

from test_live_colony import HOUR, T0, FakeClient, cfg

SYMS = ["BTCUSD", "ETHUSD", "SOLUSD", "NEARUSD", "OPUSD", "LINKUSD"]


def calls_of(text):
    return [(c.symbol, c.side) for c in parse_calls(Post("who", "1", 0, text), SYMS)]


def test_a_post_names_coins_and_leans_one_way():
    assert calls_of("$SOL looks ready to rip 🚀 loading here") == [("SOLUSD", 1)]
    assert calls_of("Shorting ETH and bitcoin, top is in") == [("ETHUSD", -1), ("BTCUSD", -1)]
    assert calls_of("Solana to 300, target soon") == [("SOLUSD", 1)]


def test_a_post_with_no_coin_or_no_lean_makes_no_call():
    assert calls_of("gm") == []
    assert calls_of("BTC is a coin") == []                 # named, no lean
    assert calls_of("buy the dip, sell the rip") == []     # lean, no coin


def test_bare_tickers_that_are_words_need_capitals_or_a_dollar():
    assert calls_of("near the top, sell everything") == []
    assert calls_of("check the link, going higher") == []
    assert calls_of("$near and OP bottomed, buying") == [("NEARUSD", 1), ("OPUSD", 1)]


def test_trust_is_the_prior_then_the_record():
    src = Source("who", prior=0.25, min_resolved=10)
    assert trust(src, 0, 0) == 0.25
    assert trust(src, 10, 7) == pytest.approx(0.4)          # 2 * 0.7 - 1
    assert trust(src, 20, 6) == pytest.approx(-0.4)         # usually wrong: faded
    assert 0.25 < trust(src, 5, 5) < 1.0                    # halfway blended


def test_signals_sum_the_open_calls_by_trust():
    calls = [Call("a", "1", 0, "BTCUSD", 1), Call("b", "2", 0, "BTCUSD", 1),
             Call("a", "3", 0, "ETHUSD", -1)]
    out = signals(calls, {"a": 0.4, "b": 0.8})
    assert out == {"BTCUSD": 1.0, "ETHUSD": -0.4}            # clipped at 1


_step = [100]


def _view(prices, signals_):
    _step[0] += 10                                          # past the cooldown every time
    candles = {s: Candle(s, 0, p, p, p, p, 1.0) for s, p in prices.items()}
    return MarketView(candles=candles, history={}, prices=prices, step=_step[0],
                      signals=signals_)


def test_a_trusted_short_call_vetoes_the_buy_and_a_deaf_agent_ignores_it():
    fast = {"lookback": 12, "entry_threshold": 0.01, "trend_filter": 24, "market_gate": 24,
            "cooldown": 1, "rank_top": 0}
    agent = MomentumAgent("m", 100.0, params=fast)
    for i in range(30):                                     # a rising tape: momentum wants in
        agent.observe([Candle("BTCUSD", i, 100 + i, 101 + i, 99 + i, 100 + i, 1.0)])
    prices = {"BTCUSD": 130.0}
    assert any(o.side == "buy" for o in agent.decide(_view(prices, {})))
    assert agent.decide(_view(prices, {"BTCUSD": -0.6})) == []   # a trusted short: no buy
    assert any(o.side == "buy" for o in agent.decide(_view(prices, {"BTCUSD": -0.3})))
    agent.params["signal_bias"] = 0                              # deaf: buys regardless
    assert any(o.side == "buy" for o in agent.decide(_view(prices, {"BTCUSD": -0.6})))


class PostingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.queue = []
        self.asked = []


def make_feed(client):
    def posts(handle, since_id=None, user_id=None):
        client.asked.append((handle, since_id, user_id))
        new = [p for p in client.queue if since_id is None or int(p.post_id) > int(since_id)]
        return "u1", new
    return LiveFeed("kraken", default_symbols("kraken"), client=client,
                    now=lambda: client.now, posts=posts)


def test_the_colony_files_calls_judges_them_and_earns_trust(tmp_path):
    client = PostingClient()
    client.now = T0 + 100 * HOUR
    feed = make_feed(client)
    src = Source("who", prior=0.25, horizon_days=1, min_resolved=2)
    journal = TradeJournal(tmp_path / "c.db")
    colony = LiveColony.open(journal, cli.build_agents(5.0, False, ""), cfg(), feed,
                             warmup=50, verbose=False, sources=[src])
    post_ts = client.now - 2 * HOUR
    client.queue.append(Post("who", "100", post_ts, "$BTC sending it higher 🚀"))
    client.queue.append(Post("who", "101", post_ts, "gm"))
    client.now += HOUR
    colony.run_once()
    calls = journal.calls()
    assert [(c.symbol, c.side) for c in calls] == [("BTCUSD", 1)]
    assert calls[0].price_at == pytest.approx(client.price("BTC/USD", 99))   # the post's bar
    assert colony.signals() == {"BTCUSD": 0.25}                             # the prior
    assert colony.source_cursor["who"] == {"since_id": "101", "user_id": "u1"}
    assert journal.load_state("live_colony")["sources"][0]["calls"] == 1

    client.now += 26 * HOUR                                # past the one-day horizon
    colony.run_once()
    judged = journal.calls(unresolved=False)
    assert len(judged) == 1 and judged[0].outcome > 0     # the tape rises: a hit
    assert colony.signals() == {}                         # nothing open any more
    s = colony.status()["sources"][0]
    assert s["handle"] == "who" and s["resolved"] == 1 and s["hit_rate"] == 1.0
    assert s["trust"] > 0.25                              # the record starts to count
    assert client.asked[-1] == ("who", "101", "u1")       # only new posts are read

    # the same post read again does not count twice
    client.queue.append(Post("who", "100", post_ts, "$BTC sending it higher 🚀"))
    client.now += HOUR
    colony.run_once()
    assert len(journal.calls()) == 1
    journal.close()


def test_a_post_filed_by_hand_reaches_the_ledger(tmp_path, monkeypatch, capsys):
    import types
    client = FakeClient()
    client.now = T0 + 100 * HOUR
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.kraken = lambda *a, **k: client
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)
    monkeypatch.setattr("cryptoarena.market.live.time.time", lambda: client.now)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    db = tmp_path / "live.db"

    def run(argv):
        sys.argv = ["cryptoarena", *argv]
        cli.main()
        return capsys.readouterr().out

    run(["live", "--once", "--db", str(db), "--warmup", "50"])
    out = run(["call", "--db", str(db), "--source", "@leshka_eth",
               "--url", "https://x.com/leshka_eth/status/2080432545221718259",
               "--text", "ETH bottomed, loading here"])
    assert "filed 1 call(s) from @leshka_eth" in out and "trust +0.25" in out
    out = run(["call", "--db", str(db), "--source", "leshka_eth",
               "--url", "https://x.com/leshka_eth/status/2080432545221718259",
               "--text", "ETH bottomed, loading here"])
    assert "no call" in out                                # the same post, filed once
    status = json.loads(run(["live", "--status", "--db", str(db)]))
    assert status["signals"] == {"ETHUSD": 0.25}
    assert status["sources"][0]["handle"] == "leshka_eth"
    assert status["sources"][0]["active"][0]["url"].endswith("2080432545221718259")
