"""The stocks floor: daily bars, one colony day per trading day, a five-day
week, and the same rituals — through the feed, the colony and the CLI."""
import json
import sys
from datetime import datetime, timedelta, timezone

from cryptoarena import cli
from cryptoarena.arena.live_colony import LiveColony
from cryptoarena.floors import FLOORS, get_floor, stock_founders
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.market.stocks import DEFAULT_STOCKS, StooqFeed

DAY = 86400
T0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())      # a Monday


class FakeStooq:
    """A daily tape with weekends skipped, growing as `now` advances."""

    def __init__(self, days: int = 400, start: int = T0):
        self.start, self.days = start, days
        self.now = start + days * DAY + 23 * 3600         # after the close of the last day
        self.base = {t: 100.0 * (1 + i / 10) for i, t in enumerate(DEFAULT_STOCKS.values())}

    def rows(self, ticker):
        out, i = [], 0
        while True:                                        # the tape grows with the clock
            ts = self.start + i * DAY
            i += 1
            if ts > self.now:
                break
            if datetime.fromtimestamp(ts, tz=timezone.utc).weekday() >= 5:
                continue
            o = self.base[ticker] * (1 + 0.0015 * i)
            c = self.base[ticker] * (1 + 0.0015 * (i + 1))
            out.append([ts, o, max(o, c) * 1.005, min(o, c) * 0.995, c, 1e6])
        return out


def make_feed(fake: FakeStooq) -> StooqFeed:
    return StooqFeed(fetch=fake.rows, now=lambda: fake.now)


def test_stooq_feed_counts_a_bar_closed_only_after_the_close():
    fake = FakeStooq(days=10)
    feed = make_feed(fake)
    bars = feed.aligned(limit=50)
    last = bars[-1][0].timestamp
    assert feed.seconds == DAY and feed.timeframe == "1d"
    assert all(datetime.fromtimestamp(b[0].timestamp, tz=timezone.utc).weekday() < 5 for b in bars)
    assert {c.symbol for c in bars[-1]} == set(DEFAULT_STOCKS)
    # the same day before 22:00 UTC: today's bar is still forming, hidden
    fake.now = last + 15 * 3600
    assert feed.aligned(limit=50)[-1][0].timestamp == last - (3 * DAY if
        datetime.fromtimestamp(last, tz=timezone.utc).weekday() == 0 else DAY)
    fake.now = last + 22 * 3600 + 60
    assert feed.aligned(limit=50)[-1][0].timestamp == last


def test_stocks_colony_lives_one_day_per_bar_and_a_five_day_week(tmp_path):
    floor = get_floor("stocks")
    cfg = floor.config(seed=1, daily_cost=0.0)
    assert cfg.steps_per_day == 1 and cfg.week_days == 5 and cfg.fee_rate == 0.0005
    fake = FakeStooq(days=420)
    journal = TradeJournal(tmp_path / "stocks.db")
    colony = LiveColony.open(journal, stock_founders(5.0), cfg, make_feed(fake),
                             warmup=250, verbose=False)
    assert colony.day == 2 and colony.hour == 0            # the founding bar closed day 1
    assert len(colony.alive[0].agent.history["SPY"]) == 250
    journal.close()

    # a fresh process a week later: five trading days, one ritual round
    fake.now += 7 * DAY
    journal = TradeJournal(tmp_path / "stocks.db")
    again = LiveColony.open(journal, [], cfg, make_feed(fake), verbose=False)
    assert again.cfg.steps_per_day == 1
    n = again.run_once()
    assert n == 5 and again.day == 7
    events = {r[0] for r in journal._conn.execute("SELECT DISTINCT event FROM survival_events")}
    assert "senior" in events                               # week 1 closed on day 5
    steps = [r[0] for r in journal._conn.execute(
        "SELECT DISTINCT step FROM market_snapshots WHERE episode = 3")]
    assert steps == [0]
    journal.close()


def test_floor_registry_and_live_urls():
    assert set(FLOORS) == {"crypto", "stocks"}
    assert FLOORS["stocks"].live_url.endswith("colony-live-stocks/colony.db")
    assert FLOORS["crypto"].live_url.endswith("colony-live/colony.db")
    ids = {a.agent_id for a in stock_founders(5.0)}
    assert ids == {a.agent_id for a in FLOORS["crypto"].build_founders(5.0)}
    assert all(a.params["trend_filter"] == 120 for a in stock_founders(5.0))


def test_cli_live_stocks_floor(tmp_path, monkeypatch, capsys):
    fake = FakeStooq(days=400)
    monkeypatch.setattr("cryptoarena.market.stocks.fetch_daily", fake.rows)
    monkeypatch.setattr("cryptoarena.market.stocks.time.time", lambda: fake.now)
    db = tmp_path / "stocks.db"
    sys.argv = ["cryptoarena", "live", "--floor", "stocks", "--once", "--db", str(db)]
    cli.main()
    out = capsys.readouterr().out
    assert "founded the colony" in out and "8 alive" in out
    sys.argv = ["cryptoarena", "live", "--status", "--db", str(db)]
    cli.main()
    status = json.loads(capsys.readouterr().out)
    assert status["alive"] == 8 and set(status["prices"]) == set(DEFAULT_STOCKS)
    saved = TradeJournal(db).load_state("live_colony")
    assert saved["timeframe"] == "1d" and saved["config"]["week_days"] == 5


def test_cboe_history_parses_us_dates_and_ohlc():
    from cryptoarena.market.stocks import parse_cboe
    text = ("DATE,OPEN,HIGH,LOW,CLOSE\n"
            "01/02/2020,3244.67,3258.14,3235.53,3257.85\n"
            "01/03/2020,3226.36,3246.15,3222.34,3234.85\n"
            "bad line\n")
    rows = parse_cboe(text)
    assert [r[4] for r in rows] == [3257.85, 3234.85]
    assert rows[0][0] == int(datetime(2020, 1, 2, tzinfo=timezone.utc).timestamp())
    assert rows[0][1:5] == [3244.67, 3258.14, 3235.53, 3257.85]


def test_nasdaq_history_parses_dollar_strings_newest_first():
    from cryptoarena.market.stocks import parse_nasdaq
    data = {"data": {"symbol": "SPY", "tradesTable": {"rows": [
        {"date": "09/19/2026", "close": "$671.23", "volume": "58,123,456",
         "open": "$669.10", "high": "$673.50", "low": "$668.02"},
        {"date": "09/18/2026", "close": "$667.00", "volume": "N/A",
         "open": "$664.00", "high": "$668.00", "low": "$663.00"},
        {"date": "bad", "close": "$1"}]}}}
    rows = parse_nasdaq(data)
    assert [r[4] for r in rows] == [667.0, 671.23]                # oldest first
    assert rows[1][1:] == [669.10, 673.50, 668.02, 671.23, 58123456.0]
    assert rows[0][5] == 0.0
