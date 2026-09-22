"""`cryptoarena live --once` is what the hourly job runs: it must found a
colony on the first call, resume it on the next, and do nothing when no
new candle has closed — all through the real CLI and a fake ccxt."""
import json
import sys
import types

from cryptoarena import cli

from test_live_colony import HOUR, T0, FakeClient


def run_cli(argv, capsys):
    sys.argv = ["cryptoarena", *argv]
    cli.main()
    return capsys.readouterr().out


def test_live_once_founds_resumes_and_idles(tmp_path, monkeypatch, capsys):
    client = FakeClient()
    client.now = T0 + 200 * HOUR
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.kraken = lambda *a, **k: client
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)
    monkeypatch.setattr("cryptoarena.market.live.time.time", lambda: client.now)
    db = tmp_path / "colony" / "live.db"

    out = run_cli(["live", "--once", "--db", str(db), "--warmup", "50"], capsys)
    assert "founded the colony on 1 new candle" in out and "9 alive" in out

    out = run_cli(["live", "--once", "--db", str(db)], capsys)
    assert "processed 0 new candle" in out                     # same hour: nothing to do

    client.now += 3 * HOUR
    out = run_cli(["live", "--once", "--db", str(db)], capsys)
    assert "processed 3 new candle" in out

    status = json.loads(run_cli(["live", "--status", "--db", str(db)], capsys))
    assert status["alive"] == 9 and status["hour"] == 4 and status["colony_equity"] > 0
    assert set(status["prices"]) == {"BTCUSD", "ETHUSD", "SOLUSD"}
    assert not (db.parent / "live.db-wal").exists()            # closed cleanly for git
