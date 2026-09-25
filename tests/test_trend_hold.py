"""Hold with a trend exit: in while the trend is up, cash while it is down."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.arena.trend_hold import Tape, hold_return, signal, simulate, window_report

DAY = 86400


def frames(paths: dict[str, list[float]]) -> dict[str, pd.DataFrame]:
    """Hourly bars from a daily path per coin (flat within the day)."""
    out = {}
    for sym, daily in paths.items():
        closes = np.repeat(np.array(daily, float), 24)
        ts = np.arange(len(closes)) * 3600 + 10 * DAY
        out[sym] = pd.DataFrame({"timestamp": ts, "open": closes, "high": closes,
                                 "low": closes, "close": closes, "volume": 1.0})
    return out


def up_then_down(days_up=60, days_down=60, rate=0.01):
    up = [100 * (1 + rate) ** i for i in range(days_up)]
    return up + [up[-1] * (1 - rate) ** i for i in range(1, days_down + 1)]


def test_it_rides_the_trend_and_steps_aside_when_it_turns():
    path = up_then_down()
    tape = Tape.from_frames(frames({"BTCUSD": path, "ETHUSD": path}))
    sig = signal(tape, "btc", 7)
    start = 10 * 24
    run = simulate(tape, sig, start, len(tape.ts) - 1, [tape.btc])
    held_to_end = path[-1] / path[10] - 1
    assert run.total > held_to_end                     # out before most of the fall
    assert run.trades == 2 and run.fees > 0            # one buy, one sell
    assert 0.3 < run.in_market < 0.7
    assert run.max_drawdown < 0.1


def test_the_signals_agree_with_their_definitions():
    btc_up, eth_down = up_then_down(120, 0), [100 * 0.99 ** i for i in range(120)]
    tape = Tape.from_frames(frames({"BTCUSD": btc_up, "ETHUSD": eth_down}))
    last = len(tape.ts) - 1
    assert signal(tape, "coin", 7)[last].tolist() == [True, False]
    assert signal(tape, "market", 7)[last].tolist() == [True, True]
    assert signal(tape, "both", 7)[last].tolist() == [True, False]
    assert signal(tape, "btc", 7)[last].tolist() == [True, False]
    assert not signal(tape, "coin", 7)[0].any()        # no history yet: stay out
    with pytest.raises(ValueError):
        signal(tape, "moon", 7)


def test_the_window_report_matches_the_colony_benchmark():
    path = up_then_down(80, 80)
    f = frames({"BTCUSD": path, "ETHUSD": path})
    tape = Tape.from_frames(f)
    rep = window_report(tape, f, [("btc", 7)], days=10, stride_days=10, warmup_bars=240)
    assert rep["windows"] > 5
    first_start = 240
    assert rep["hold"]["worst"] <= hold_return(tape, first_start, first_start + 239, [0, 1]) + 1e-9
    assert rep["btc-7d"]["worst"] > rep["hold"]["worst"]   # it stepped aside in the fall
