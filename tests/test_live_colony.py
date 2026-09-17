"""The colony on real-world time: closed candles only, state that survives
a process restart, and the same daily rituals when the UTC day rolls over."""
import math

import pytest

from cryptoarena.arena.live_colony import LiveColony
from cryptoarena.arena.survival import SurvivalConfig
from cryptoarena.cli import build_agents
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.market.live import LiveFeed, default_symbols

HOUR = 3600
T0 = 1_760_000_000 // 86400 * 86400          # a UTC midnight


class FakeClient:
    """A CCXT-shaped client serving a deterministic hourly tape that keeps
    growing as `now` advances; the last row is always the candle still
    being formed (open time == the current hour)."""

    def __init__(self, start: int = T0, base: dict[str, float] | None = None):
        self.start = start
        self.base = base or {"BTC/USD": 60_000.0, "ETH/USD": 3_000.0, "SOL/USD": 150.0}
        self.now = start + 6 * HOUR
        self.calls = 0

    def price(self, symbol: str, i: int) -> float:
        # a trend with wiggles, so the trend followers actually trade
        return self.base[symbol] * (1 + 0.004 * i + 0.01 * math.sin(i / 3))

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        assert timeframe == "1h"
        last_open = self.now // HOUR * HOUR                 # the forming candle
        first = self.start if since is None else max(self.start, since // 1000)
        rows = []
        i0 = (first - self.start) // HOUR
        for i in range(int(i0), int((last_open - self.start) // HOUR) + 1):
            o, c = self.price(symbol, i), self.price(symbol, i + 1)
            rows.append([(self.start + i * HOUR) * 1000, o, max(o, c) * 1.001,
                         min(o, c) * 0.999, c, 50.0])
        if not limit:
            return rows
        return rows[:limit] if since is not None else rows[-limit:]   # as CCXT pages


def make_feed(client: FakeClient) -> LiveFeed:
    return LiveFeed("kraken", default_symbols("kraken"), client=client, now=lambda: client.now)


def cfg(**kw) -> SurvivalConfig:
    base = dict(budget=5.0, seed=1, endogenous=False, daily_cost=0.0)
    base.update(kw)
    return SurvivalConfig(**base)


def test_feed_hides_the_forming_candle():
    client = FakeClient()
    feed = make_feed(client)
    bars = feed.aligned(limit=10)
    assert len(bars) == 6                                   # 6 closed, the 7th is forming
    assert bars[-1][0].timestamp == client.now - HOUR
    assert {c.symbol for c in bars[-1]} == {"BTCUSD", "ETHUSD", "SOLUSD"}
    since = bars[-1][0].timestamp
    assert feed.aligned(limit=10, since=since) == []        # nothing new yet
    client.now += HOUR
    new = feed.aligned(limit=10, since=since)
    assert [b[0].timestamp for b in new] == [since + HOUR]


def test_first_run_warms_up_then_trades_the_latest_bar(tmp_path):
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    journal = TradeJournal(tmp_path / "live.db")
    colony = LiveColony.open(journal, build_agents(5.0, False, ""), cfg(), make_feed(client),
                             warmup=100, verbose=False)
    assert colony.clock == 1                                  # exactly one bar traded
    assert colony.last_ts == client.now - HOUR
    founder = colony.alive[0].agent
    assert len(founder.history["BTCUSD"]) == 100             # warmed with the tape
    assert journal.load_state("live_colony")["last_ts"] == colony.last_ts
    assert colony.run_once() == 0                             # idempotent within the hour
    journal.close()


def test_state_survives_a_restart_and_the_day_rolls_over(tmp_path):
    client = FakeClient()
    client.now = T0 + 120 * HOUR                              # midnight: first closed bar opened at 23:00
    db = tmp_path / "live.db"
    journal = TradeJournal(db)
    colony = LiveColony.open(journal, build_agents(5.0, False, ""), cfg(), make_feed(client),
                             warmup=100, verbose=False)
    assert colony.day == 2 and colony.hour == 0               # day 1 was that single 23:00 bar
    assert journal._conn.execute(
        "SELECT COUNT(*) FROM survival_events WHERE event='survived' AND day=1").fetchone()[0] == 7
    journal.close()

    # a fresh process, six hours later: everything comes back and the clock continues
    client.now += 6 * HOUR
    journal = TradeJournal(db)
    colony2 = LiveColony.open(journal, build_agents(5.0, False, ""), cfg(budget=99.0),
                              make_feed(client), verbose=False)
    assert colony2.cfg.budget == 5.0                          # the saved config wins
    ids = {i.agent_id for i in colony2.alive}
    assert ids == {i.agent_id for i in colony.alive}
    assert colony2.clock == colony.clock and colony2.day == 2 and colony2.hour == 0
    n = colony2.run_once()
    assert n == 6 and colony2.hour == 6 and colony2.clock == colony.clock + 6
    for ind in colony2.alive:
        assert len(ind.agent.history["BTCUSD"]) == 106

    # the same tape, replayed from the same state, gives the same wallets
    journal.close()
    journal = TradeJournal(db)
    again = LiveColony.open(journal, [], cfg(), make_feed(client), verbose=False)
    for a, b in zip(colony2.alive, again.alive):
        assert a.agent.wallet.cash == pytest.approx(b.agent.wallet.cash)
        assert a.agent.wallet.positions == pytest.approx(b.agent.wallet.positions)
        assert a.agent.get_params() == b.agent.get_params()
        assert getattr(a.agent, "_last_trade_step", None) == getattr(b.agent, "_last_trade_step", None)

    # a full day later the rituals ran once: summaries for day 2, day 3 open
    client.now += 18 * HOUR
    assert again.run_once() == 18
    assert again.day == 3 and again.hour == 0
    days = [r[0] for r in journal._conn.execute(
        "SELECT DISTINCT episode FROM episode_summary ORDER BY episode")]
    assert days == [1, 2]
    steps = [r[0] for r in journal._conn.execute(
        "SELECT DISTINCT step FROM market_snapshots WHERE episode = 2 ORDER BY step")]
    assert steps == list(range(24))                           # the day's tape reads 0..23
    assert again.status()["alive"] == 7
    journal.close()


def test_missed_hours_are_caught_up_in_order(tmp_path):
    client = FakeClient()
    client.now = T0 + 30 * HOUR
    journal = TradeJournal(tmp_path / "live.db")
    colony = LiveColony.open(journal, build_agents(5.0, False, ""), cfg(), make_feed(client),
                             warmup=20, verbose=False)
    before = colony.last_ts
    client.now += 5 * HOUR                                    # the cron skipped four ticks
    assert colony.run_once() == 5
    assert colony.last_ts == before + 5 * HOUR
    journal.close()


def test_a_week_on_the_tape_hires_and_holds_the_happy_hour(tmp_path):
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    journal = TradeJournal(tmp_path / "live.db")
    colony = LiveColony.open(journal, build_agents(5.0, False, ""),
                             cfg(daily_target=0.0, clone_at=1.02, min_child_budget=0.05),
                             make_feed(client), warmup=100, verbose=False)
    client.now += 8 * 24 * HOUR
    colony.run_once()
    events = {r[0] for r in journal._conn.execute("SELECT DISTINCT event FROM survival_events")}
    assert {"party", "senior", "target_hit"} <= events
    assert colony.day == 10                                   # day 1 was one bar, then 8 full days
    assert len(colony.result.alive_per_day) == colony.day - 1
    journal.close()
