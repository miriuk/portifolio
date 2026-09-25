"""The forecast harness: nobody sees tomorrow, and the scoring is honest."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.arena.trend_hold import Tape
from cryptoarena.forecast import benchmarks, daily_closes, evaluate, walk_forward
from cryptoarena.forecast.models import Drift, _lag_features

DAY = 86400


def tape_from_daily(daily):
    closes = np.repeat(np.asarray(daily, float), 24)
    ts = np.arange(len(closes)) * 3600 + 30 * DAY
    f = {"BTCUSD": pd.DataFrame({"timestamp": ts, "open": closes, "high": closes, "low": closes,
                                 "close": closes, "volume": 1.0})}
    return Tape.from_frames(f)


class Spy:
    name = "spy"

    def __init__(self, daily):
        self.daily, self.seen = daily, []

    def predict(self, contexts, horizon):
        for c in contexts:
            assert np.array_equal(c, self.daily.close[:len(c)])     # the past, exactly
            self.seen.append(len(c))
        return np.ones(len(contexts))


def test_every_prediction_sees_only_the_past():
    path = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.03, 200)))
    tape = tape_from_daily(path)
    daily = daily_closes(tape)
    spy = Spy(daily)
    preds = walk_forward(daily, spy, start=50, horizon=7, batch=16)
    assert spy.seen == list(range(51, len(daily.close) + 1))   # day d sees closes 0..d
    assert np.isnan(preds[:50]).all() and (preds[50:] == 1).all()


def test_a_model_that_knows_the_future_would_be_caught_by_the_score():
    rng = np.random.default_rng(2)
    path = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 400)))
    tape = tape_from_daily(path)
    daily = daily_closes(tape)
    n, h = len(daily.close), 7
    oracle = np.full(n, np.nan)
    oracle[:n - h] = np.log(daily.close[h:] / daily.close[:n - h])
    oracle[n - h:] = 0.01
    v = evaluate(tape, daily, oracle, start=50, horizon=h, name="oracle")
    assert v.hit_rate == 1.0 and v.ic > 0.99
    noise = evaluate(tape, daily, rng.normal(0, 1, n), start=50, horizon=h, name="noise")
    assert abs(noise.ic) < 0.2 and 0.3 < noise.hit_rate < 0.7
    flat = np.where(np.arange(n) % 2 == 0, 0.0, oracle)          # no view on even days
    half = evaluate(tape, daily, flat, start=50, horizon=h, name="half")
    assert half.hit_rate == 1.0 and 0.45 < half.calls < 0.55      # a zero is no call, not a miss
    hold, trend = benchmarks(tape, daily, 50)
    assert v.cagr > hold.cagr and v.cagr > noise.cagr


def test_drift_follows_the_long_run_and_the_lag_features_look_back_only():
    up = 100 * 1.01 ** np.arange(60)
    assert Drift(30).predict([up], 7)[0] == pytest.approx(7 * np.log(1.01))
    r = np.arange(1, 41, dtype=float)
    X = _lag_features(r, 5)
    assert X[10, :5].tolist() == [11, 10, 9, 8, 7]                 # today, then back
    assert X[10, 5] == pytest.approx(sum(range(5, 12)))            # the last 7 days
