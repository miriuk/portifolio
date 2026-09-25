"""Forecasters from open-source projects, behind one interface.

- `StatsModel` — Nixtla's statsforecast (github.com/Nixtla/statsforecast):
  AutoARIMA, AutoETS, AutoTheta on the log price.
- `BoostedLags` — the machine-learning setup of the crypto forecasting
  benchmark (github.com/StephanAkkerman/crypto-forecasting-benchmark):
  gradient boosting (LightGBM) on lagged log returns, retrained on an
  expanding window every `retrain_every` days.
- `ChronosModel` — Amazon's pretrained Chronos-Bolt
  (github.com/amazon-science/chronos-forecasting), zero-shot: no training,
  the median forecast of the price path.
- `Drift` — the no-skill baseline: the mean daily log return of the
  context, times the horizon.

Each takes daily closes ending today and returns the predicted log return
over the horizon; none ever sees a price after the day it predicts from.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class Drift:
    def __init__(self, lookback: int = 365):
        self.lookback = lookback
        self.name = f"drift ({lookback}d mean)"

    def predict(self, contexts, horizon):
        out = []
        for c in contexts:
            r = np.diff(np.log(c[-self.lookback - 1:]))
            out.append(float(r.mean()) * horizon if len(r) else 0.0)
        return np.array(out)


class StatsModel:
    """statsforecast on the log price; each context is one series."""

    def __init__(self, model: str = "AutoARIMA", n_jobs: int = -1):
        self.model, self.n_jobs = model, n_jobs
        self.name = f"statsforecast {model}"

    def predict(self, contexts, horizon):
        from statsforecast import StatsForecast
        from statsforecast import models as sm
        frames = []
        for k, c in enumerate(contexts):
            frames.append(pd.DataFrame({"unique_id": k, "ds": np.arange(len(c)),
                                        "y": np.log(c)}))
        df = pd.concat(frames, ignore_index=True)
        sf = StatsForecast(models=[getattr(sm, self.model)()], freq=1, n_jobs=self.n_jobs)
        fc = sf.forecast(df=df, h=horizon)
        col = [c for c in fc.columns if c not in ("unique_id", "ds")][0]
        last_step = fc.groupby("unique_id")[col].last()
        return np.array([last_step.loc[k] - np.log(c[-1]) for k, c in enumerate(contexts)])


def _lag_features(logret: np.ndarray, lags: int) -> np.ndarray:
    """Row t: the last `lags` daily returns ending at t, plus 7- and
    28-day sums and 28-day volatility, all known at t's close."""
    n = len(logret)
    X = np.full((n, lags + 3), np.nan)
    for k in range(lags):
        X[k:, k] = logret[:n - k] if k else logret
    s = pd.Series(logret)
    X[:, lags] = s.rolling(7).sum().to_numpy()
    X[:, lags + 1] = s.rolling(28).sum().to_numpy()
    X[:, lags + 2] = s.rolling(28).std().to_numpy()
    return X


class BoostedLags:
    def __init__(self, lags: int = 28, retrain_every: int = 30, min_train: int = 300, seed: int = 7):
        self.lags, self.retrain_every, self.min_train, self.seed = lags, retrain_every, min_train, seed
        self.name = "LightGBM on lagged returns"
        self._model, self._since = None, 10**9          # days since the last fit

    def _fit(self, closes, horizon):
        import lightgbm as lgb
        r = np.diff(np.log(closes))
        X = _lag_features(r, self.lags)
        y = np.full(len(r), np.nan)
        csum = np.concatenate([[0.0], np.cumsum(r)])
        y[:len(r) - horizon] = csum[horizon + 1:len(r) + 1] - csum[1:len(r) - horizon + 1]
        ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)       # only targets already realised
        if ok.sum() < self.min_train:
            return None
        params = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15,
                  "min_data_in_leaf": 30, "bagging_fraction": 0.8, "bagging_freq": 1,
                  "feature_fraction": 0.8, "seed": self.seed, "verbose": -1,
                  "num_threads": 1, "deterministic": True}
        return lgb.train(params, lgb.Dataset(X[ok], y[ok]), num_boost_round=200)

    def predict(self, contexts, horizon):
        out = []
        for c in contexts:                              # in date order, one per day
            if self._model is None or self._since >= self.retrain_every:
                self._model, self._since = self._fit(c, horizon), 0
            self._since += 1
            if self._model is None:
                out.append(0.0)
                continue
            X = _lag_features(np.diff(np.log(c)), self.lags)[-1:]
            out.append(float(self._model.predict(X)[0]) if not np.isnan(X).any() else 0.0)
        return np.array(out)


class ChronosModel:
    """Chronos-Bolt, zero-shot. Needs `chronos-forecasting` (PyTorch) and
    the Hugging Face hub to fetch the weights the first time."""

    def __init__(self, model_id: str = "amazon/chronos-bolt-small", context_days: int = 512):
        self.model_id, self.context_days = model_id, context_days
        self.name = f"Chronos {model_id.split('/')[-1]}"
        self._pipe = None

    def predict(self, contexts, horizon):
        import torch
        from chronos import BaseChronosPipeline
        if self._pipe is None:
            self._pipe = BaseChronosPipeline.from_pretrained(self.model_id, device_map="cpu",
                                                             torch_dtype=torch.float32)
        inputs = [torch.tensor(c[-self.context_days:], dtype=torch.float32) for c in contexts]
        quantiles, _ = self._pipe.predict_quantiles(inputs, prediction_length=horizon,
                                                    quantile_levels=[0.5])
        median = quantiles[:, horizon - 1, 0].numpy()
        return np.log(median / np.array([c[-1] for c in contexts]))
