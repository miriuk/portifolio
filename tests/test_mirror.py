"""The practice-account mirror: the account ends up holding what the
colony holds, and running it again never doubles a trade."""
import base64
import io
import json
import sys
import types
import urllib.error

import pytest

from cryptoarena.broker import fx
from cryptoarena.broker.mirror import colony_holdings, mirror, plan, report, resolve
from cryptoarena.broker.trading212 import DEMO, OrderUncertain, PracticeAccount

INSTRUMENTS = [{"ticker": f"{s}_US_EQ", "shortName": s, "currencyCode": "USD", "type": "STOCK"}
               for s in ("AAPL", "MSFT", "NVDA", "AMZN")] + [
               {"ticker": "TSCOl_EQ", "shortName": "TSCO", "currencyCode": "GBX", "type": "STOCK"}]
UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN"]


class FakeDemo:
    def __init__(self, positions=None, pending=None, errors=None):
        self._positions = list(positions or [])
        self.pending = list(pending or [])
        self.errors = list(errors or [])
        self.requests = []

    def __call__(self, req, timeout=None):
        assert req.full_url.startswith(DEMO)                      # the practice host, always
        path = req.full_url[len(DEMO):]
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), path, body, dict(req.header_items())))
        if req.get_method() == "POST":
            if self.errors:
                err = self.errors.pop(0)
                if isinstance(err, int):
                    raise urllib.error.HTTPError(req.full_url, err, "err", {}, io.BytesIO(b"{}"))
                raise err
            # the order fills: the account now holds it
            t, q = body["ticker"], body["quantity"]
            for p in self._positions:
                if p["ticker"] == t:
                    p["quantity"] += q
                    p["quantityAvailableForTrading"] += q
                    break
            else:
                self._positions.append({"ticker": t, "quantity": q, "quantityAvailableForTrading": q})
            return io.BytesIO(json.dumps({"id": len(self.requests), "status": "FILLED"}).encode())
        data = {"/metadata/instruments": INSTRUMENTS, "/positions": self._positions,
                "/orders": self.pending,
                "/account/summary": {"currency": "GBP", "cash": {"availableToTrade": 900.0},
                                     "totalValue": 1000.0}}
        return io.BytesIO(json.dumps(data[path]).encode())

    @property
    def orders(self):
        return [r[2] for r in self.requests if r[0] == "POST"]


def account(fake):
    return PracticeAccount("key", "secret", opener=fake, sleep=lambda s: None)


def test_only_the_practice_host_exists():
    acc = account(FakeDemo())
    acc.account_summary()
    assert acc.base == "https://demo.trading212.com/api/v0/equity"
    import cryptoarena.broker.trading212 as t
    assert "live.trading212" not in open(t.__file__).read()
    assert fake_auth(acc) == "Basic " + base64.b64encode(b"key:secret").decode()
    with pytest.raises(ValueError):
        PracticeAccount.from_env({})


def fake_auth(acc):
    return acc._auth


def test_the_colony_holdings_sum_the_living_agents():
    state = {"population": [
        {"died_day": None, "agent": {"wallet": {"positions": {"AAPL": 1.5, "SPY": 0.2}}}},
        {"died_day": None, "agent": {"wallet": {"positions": {"AAPL": 0.5, "NVDA": 0.0}}}},
        {"died_day": 3, "agent": {"wallet": {"positions": {"MSFT": 9.0}}}}]}
    assert colony_holdings(state) == {"AAPL": 2.0, "SPY": 0.2}


def test_a_second_run_sends_nothing():
    fake = FakeDemo()
    target = {"AAPL": 2.004, "NVDA": 1.5, "SPY": 0.3}
    steps = mirror(account(fake), target, UNIVERSE, execute=True)
    assert fake.orders == [{"ticker": "AAPL_US_EQ", "quantity": 2.0, "extendedHours": False},
                           {"ticker": "NVDA_US_EQ", "quantity": 1.5, "extendedHours": False}]
    assert any(s.symbol == "SPY" and s.action == "missing" for s in steps)   # stays on paper
    mirror(account(fake), target, UNIVERSE, execute=True)
    assert len(fake.orders) == 2                                             # already in line


def test_pending_orders_count_as_held():
    fake = FakeDemo(pending=[{"ticker": "AAPL_US_EQ", "quantity": 2.0, "side": "BUY",
                              "filledQuantity": 0.0}])
    mirror(account(fake), {"AAPL": 2.0}, UNIVERSE, execute=True)
    assert fake.orders == []                  # yesterday's order still queued for the open


def test_sells_first_capped_and_other_tickers_untouched():
    fake = FakeDemo(positions=[
        {"ticker": "MSFT_US_EQ", "quantity": 3.0, "quantityAvailableForTrading": 2.0},
        {"ticker": "TSCOl_EQ", "quantity": 10.0, "quantityAvailableForTrading": 10.0}])
    mirror(account(fake), {"AMZN": 1.0}, UNIVERSE, execute=True)
    assert fake.orders[0] == {"ticker": "MSFT_US_EQ", "quantity": -2.0, "extendedHours": False}
    assert fake.orders[1]["ticker"] == "AMZN_US_EQ"
    assert all(o["ticker"] != "TSCOl_EQ" for o in fake.orders)             # not the floor's


def test_an_uncertain_order_stops_the_run():
    fake = FakeDemo(errors=[408])
    steps = mirror(account(fake), {"AAPL": 1.0, "NVDA": 1.0}, UNIVERSE, execute=True)
    assert len(fake.orders) == 1 and [s.action for s in steps][-1] == "uncertain"


def test_a_rehearsal_sends_nothing_and_a_pause_reads_nothing():
    fake = FakeDemo()
    steps = mirror(account(fake), {"AAPL": 1.0}, UNIVERSE, execute=False)
    assert fake.orders == [] and steps[-1].action == "would_buy"
    fake = FakeDemo()
    mirror(account(fake), {"AAPL": 1.0}, UNIVERSE, execute=True, paused=True)
    assert fake.requests == []
    assert "virtual money" in report(steps)


def test_symbols_resolve_to_trading212_tickers():
    assert resolve(INSTRUMENTS, "AAPL") == "AAPL_US_EQ"
    assert resolve(INSTRUMENTS, "SPY") is None
    orders, _ = plan({"AAPL": 0.004}, UNIVERSE, INSTRUMENTS, [], [])
    assert orders == []                                                      # below 0.01 share


def test_pounds_to_dollars_from_the_ecb():
    xml = "<Cube currency='USD' rate='1.1700'/><Cube currency='GBP' rate='0.8700'/>"
    assert fx.parse_ecb(xml) == pytest.approx(1.17 / 0.87)
    assert fx.usd_per_gbp(lambda url: b'{"rates": {"USD": 1.34}}') == 1.34
    def ecb_only(url):
        if "frankfurter" in url:
            raise OSError("down")
        return xml.encode()
    assert fx.usd_per_gbp(ecb_only) == pytest.approx(1.17 / 0.87)


def test_a_pound_deposit_founds_the_stocks_colony(tmp_path, monkeypatch, capsys):
    from cryptoarena import cli
    monkeypatch.setattr("cryptoarena.broker.fx.usd_per_gbp", lambda: 1.35)
    seen = {}

    class Feed:
        symbols = {"SPY": "SPY"}
        seconds = 86400
        timeframe = "1d"
        exchange_id = "nasdaq"

    def fake_open(journal, founders, cfg, feed, **kw):
        seen["budget"] = cfg.budget
        seen["n"] = len(founders)
        raise SystemExit(0)
    monkeypatch.setattr("cryptoarena.arena.live_colony.LiveColony.open", fake_open)
    monkeypatch.setattr("cryptoarena.floors.FLOORS", {**__import__("cryptoarena.floors").floors.FLOORS})
    from cryptoarena import floors
    monkeypatch.setattr(floors.FLOORS["stocks"], "make_feed", lambda **kw: Feed())
    sys.argv = ["cryptoarena", "live", "--floor", "stocks", "--once", "--db",
                str(tmp_path / "s.db"), "--deposit-gbp", "1000"]
    with pytest.raises(SystemExit):
        cli.main()
    assert seen["n"] == 9 and seen["budget"] == pytest.approx(round(1000 * 1.35 / 9, 2))
    assert "deposit £1,000.00 at 1.3500 USD/GBP" in capsys.readouterr().out
