"""The lookahead audit: a scrambled future must not change a past decision,
and fills can wait for the next bar's open."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.agents.base import TradingAgent
from cryptoarena.arena import lookahead
from cryptoarena.arena.backtest import TapeSlice, load_tape
from cryptoarena.arena.lookahead import (audit_colony, audit_series, delay_report, format_delay,
                                         scramble_after, scramble_sentiment, universe_check)
from cryptoarena.arena.survival import SurvivalConfig, run_survival
from cryptoarena.arena.trend_hold import Tape, simulate
from cryptoarena.cli import build_agents
from cryptoarena.market.candle import Candle
from cryptoarena.market.exchange import NextOpenExchange, Order
from test_backtest import write_tape


def frames_of(tmp_path, bars=720 + 24 * 8 + 1):
    write_tape(tmp_path, bars=bars)
    return load_tape(tmp_path)


def test_scramble_keeps_the_past_and_changes_the_future(tmp_path):
    frames = frames_of(tmp_path)
    cut = 800
    fr = scramble_after(frames, cut, seed=3)
    for sym, df in frames.items():
        pd.testing.assert_frame_equal(df.iloc[:cut + 1], fr[sym].iloc[:cut + 1])
        assert not np.allclose(df["close"].iloc[cut + 1:], fr[sym]["close"].iloc[cut + 1:])
        later = fr[sym].iloc[cut + 1:]
        assert (later["high"] >= later[["open", "close"]].max(axis=1) - 1e-9).all()
    sent = {d: d % 100 for d in range(19_000, 19_010)}
    s2 = scramble_sentiment(sent, 19_004 * 86400 + 5, seed=1)
    assert all(s2[d] == sent[d] for d in range(19_000, 19_005))
    assert sorted(s2.values()) == sorted(sent.values())


def test_the_founders_never_read_the_future(tmp_path):
    frames = frames_of(tmp_path)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    audit = audit_colony(frames, lambda: build_agents(5.0, False, ""), cfg, start=0, days=8,
                         warmup_bars=720)
    assert audit.clean
    assert sum(p.events_checked for p in audit.probes) > 0


class Peeker(TradingAgent):
    """Buys when the market's leak says tomorrow is higher."""

    def decide(self, view):
        c = view.candles["BTCUSD"]
        if c.volume > c.close and self.wallet.cash > 1:
            return [Order(self.agent_id, "BTCUSD", "buy", 1.0, reason="peek")]
        held = self.wallet.positions.get("BTCUSD", 0.0)
        return [Order(self.agent_id, "BTCUSD", "sell", held, reason="peek")] if held > 0 else []


class LeakySlice(TapeSlice):
    """A market bug: each candle's volume carries the next bar's close."""

    def next_candles(self):
        out = super().next_candles()
        return [Candle(c.symbol, c.timestamp, c.open, c.high, c.low, c.close,
                       (self.next_open(c.symbol, c.timestamp) or 0.0) * 1.0001) for c in out]


def test_a_leak_is_caught(tmp_path, monkeypatch):
    frames = frames_of(tmp_path)
    monkeypatch.setattr(lookahead, "TapeSlice", LeakySlice)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    audit = audit_colony(frames, lambda: [Peeker("peeker-1", 5.0)], cfg, start=0, days=8,
                         warmup_bars=720)
    assert not audit.clean
    assert any("trade" in (p.mismatch or "") or "event" in (p.mismatch or "")
               for p in audit.probes)


def test_series_audit_flags_a_shifted_signal(tmp_path):
    frames = frames_of(tmp_path)

    def honest(fr):
        c = fr["BTCUSD"].set_index("timestamp")["close"]
        return c.pct_change(24)

    def leaky(fr):
        c = fr["BTCUSD"].set_index("timestamp")["close"]
        return c.shift(-1) / c - 1

    cuts = [760, 820]
    assert audit_series(honest, frames, cuts) == []
    assert len(audit_series(leaky, frames, cuts)) == 2


def test_next_open_fills_at_the_next_bar(tmp_path):
    frames = frames_of(tmp_path, bars=30)
    market = TapeSlice(frames, 0, 10)
    bar = [c for c in market.next_candles() if c.symbol == "ETHUSD"][0]
    nxt = float(frames["ETHUSD"]["open"].iloc[1])
    assert market.next_open("ETHUSD", bar.timestamp) == pytest.approx(nxt)
    ex = NextOpenExchange(market.next_open, fee_rate=0.0, slippage_base=0.0, seed=1)
    fill = ex.execute(Order("a", "ETHUSD", "buy", 100.0), bar)
    assert fill.price == pytest.approx(nxt) and fill.timestamp == bar.timestamp
    for _ in range(9):
        market.next_candles()
    last = float(frames["ETHUSD"]["open"].iloc[10])          # one row past the window is kept
    assert market.next_open("ETHUSD", 0) == pytest.approx(last)
    end = TapeSlice({"ETHUSD": frames["ETHUSD"].iloc[:3]}, 0, 3)
    for _ in range(3):
        c = end.next_candles()[0]
    assert end.next_open("ETHUSD", c.timestamp) is None      # past the tape: the close stands in
    assert ex.__class__(end.next_open, fee_rate=0.0, slippage_base=0.0).execute(
        Order("a", "ETHUSD", "buy", 100.0), c).price == pytest.approx(c.close)


def test_delayed_fills_through_the_backtest(tmp_path):
    frames = frames_of(tmp_path, bars=720 + 24 * 10 + 1)
    for df in frames.values():                  # the synthetic tape opens where it closed: add a gap
        df["open"] *= 1.003
        df["high"] = df[["high", "open"]].max(axis=1)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    rep = delay_report(frames, lambda: build_agents(5.0, False, ""), cfg, days=10, stride_days=10,
                       warmup_bars=720)
    assert rep["close"]["windows"] == rep["next_open"]["windows"] == 1
    assert rep["close"]["hold_mean"] == rep["next_open"]["hold_mean"]
    assert rep["close"]["colony_mean"] != rep["next_open"]["colony_mean"]
    assert "next open" in format_delay(rep)
    with pytest.raises(ValueError, match="next bar"):
        run_survival(build_agents(5.0, False, ""), __import__(
            "cryptoarena.learning.memory", fromlist=["TradeJournal"]).TradeJournal(":memory:"),
            SurvivalConfig(days=1, seed=1, endogenous=False, fill="next_open"), verbose=False)


def test_trend_exit_can_fill_at_the_next_open():
    ts = np.arange(4) * 86400
    close = np.array([[10.0], [11.0], [12.0], [13.0]])
    opn = np.array([[10.0], [10.5], [11.5], [12.5]])
    tape = Tape(["SPY"], ts, close, opn, lead_symbol="SPY", bars_per_day=1)
    sig = np.ones_like(close, dtype=bool)
    at_close = simulate(tape, sig, 0, 3, [0], fee=0.0)
    at_open = simulate(tape, sig, 0, 3, [0], fee=0.0, fill="next_open")
    assert at_close.total == pytest.approx(13 / 10 - 1)
    assert at_open.total == pytest.approx(13 / 10.5 - 1)          # bought at the next open
    assert at_open.curve[0] == 1.0                                # nothing held on day one
    with pytest.raises(ValueError):
        simulate(tape, sig, 0, 3, [0], fill="later")


def test_universe_check_counts_a_symbol_that_vanishes(tmp_path):
    frames = frames_of(tmp_path, bars=720 + 24 * 10 + 1)
    df = frames["SOLUSD"].copy()
    df.loc[df.index > 720 + 24 * 5, ["open", "high", "low", "close"]] = np.nan
    frames["SOLUSD"] = df
    out = universe_check(frames, days=10, stride_days=10, warmup_bars=720, bars_per_day=24)
    assert out == {"windows": 1, "left_out": 1, "symbols": {"SOLUSD": 1}}
