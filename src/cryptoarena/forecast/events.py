"""Course 5 of the academy: financial machine learning, done carefully.

Chapter 7 of *Algorithmic Trading with Python* (Chris Conlan, 2020),
after Marcos López de Prado's *Advances in Financial Machine Learning*
(2018), written here from their descriptions (the book's code is freeware
for personal use only and is not copied):

- **CUSUM filter**: do not sample every day; sample when the cumulative
  move since the last sample passes a threshold, up or down. Those are
  the *events* worth a decision;
- **triple-barrier labels**: from each event, the first of three barriers
  the price touches: a profit take above, a stop below (both scaled by
  the recent volatility), or a time limit. +1, -1, or the sign of the
  return at the time limit;
- **average uniqueness**: labels whose windows overlap share information;
  each sample is weighted by how much of its window it has alone, so a
  burst of overlapping events does not count many times;
- **walk-forward with a purge**: train only on events whose label was
  known before the test year starts, test on that year, move on.

`ml_exam` runs the whole pipeline with a random forest on price and
volume features and reports, per test year, the accuracy against simply
guessing the most common label, and what the events the model liked did
next against all events.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def cusum_events(log_price: pd.Series, threshold: float) -> pd.Index:
    """Index labels where the cumulative log move since the last event
    passes `threshold`, upward or downward."""
    r = log_price.diff().dropna()
    up = down = 0.0
    out = []
    for t, x in r.items():
        up, down = max(0.0, up + x), min(0.0, down + x)
        if up > threshold:
            up = 0.0
            out.append(t)
        elif down < -threshold:
            down = 0.0
            out.append(t)
    return pd.Index(out)


def triple_barrier(close: pd.Series, events: pd.Index, width: pd.Series,
                   horizon: int = 20) -> pd.DataFrame:
    """For each event: label (+1 profit barrier first, -1 stop first, else
    the sign of the return at the time limit), the row where the label was
    decided (`end`), and the return to it (`ret`). Barriers sit at ± width
    (a log move) from the event's close."""
    pos = {t: i for i, t in enumerate(close.index)}
    lp = np.log(close.to_numpy(float))
    rows = []
    for t in events:
        i = pos.get(t)
        w = float(width.get(t, np.nan))
        if i is None or not w == w or w <= 0 or i + 1 >= len(lp):
            continue
        j_end = min(i + horizon, len(lp) - 1)
        path = lp[i + 1:j_end + 1] - lp[i]
        hit_up = np.where(path >= w)[0]
        hit_dn = np.where(path <= -w)[0]
        first_up = hit_up[0] if len(hit_up) else None
        first_dn = hit_dn[0] if len(hit_dn) else None
        if first_up is not None and (first_dn is None or first_up < first_dn):
            k, label = first_up, 1
        elif first_dn is not None:
            k, label = first_dn, -1
        else:
            k, label = len(path) - 1, int(np.sign(path[-1])) or -1
        rows.append({"t": t, "end": close.index[i + 1 + k], "label": label,
                     "ret": float(np.exp(path[k]) - 1)})
    return pd.DataFrame(rows).set_index("t") if rows else pd.DataFrame(
        columns=["end", "label", "ret"])


def average_uniqueness(spans: pd.DataFrame, index: pd.Index) -> pd.Series:
    """Per event (rows of `spans`, with column `end`, indexed by start):
    the mean, over the bars of its window, of 1 / (events alive on that
    bar). An event alone all the way scores 1."""
    pos = {t: i for i, t in enumerate(index)}
    n = len(index)
    alive = np.zeros(n)
    bounds = []
    for t, row in spans.iterrows():
        a, b = pos[t], pos[row["end"]]
        alive[a:b + 1] += 1
        bounds.append((a, b))
    return pd.Series([float(np.mean(1.0 / alive[a:b + 1])) for a, b in bounds], index=spans.index)


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Price and volume features known at each close (rows: dates)."""
    c = df["close"].astype(float)
    lc = np.log(c)
    r = lc.diff()
    out = {f"ret_{n}": lc - lc.shift(n) for n in (5, 20, 60, 120)}
    out.update({f"vol_{n}": r.rolling(n).std() for n in (20, 60)})
    out["dist_ma50"] = c / c.rolling(50).mean() - 1
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfv = df["volume"] * (2 * df["close"] - df["high"] - df["low"]) / rng
    out["cmf_20"] = mfv.rolling(20).sum() / df["volume"].rolling(20).sum()
    out["volume_z"] = (df["volume"] - df["volume"].rolling(60).mean()) / df["volume"].rolling(60).std()
    return pd.DataFrame(out)


@dataclass
class YearScore:
    year: int
    events: int
    accuracy: float
    base_rate: float               # always guessing the most common label in training
    liked_ret: float               # mean return of events the model called +1
    all_ret: float                 # mean return of all test events


def build_events(frames: dict[str, pd.DataFrame], threshold_vols: float = 2.0,
                 horizon: int = 20, barrier_vols: float = 1.0) -> pd.DataFrame:
    """Events, labels, features and uniqueness weights for every symbol."""
    parts = []
    for sym, df in frames.items():
        df = df.dropna(subset=["close"]).set_index("timestamp")
        if len(df) < 300:
            continue
        c = df["close"].astype(float)
        lc = np.log(c)
        daily = lc.diff().rolling(60).std()
        # the CUSUM step: a few typical days, measured on the first year only
        h = float(threshold_vols * lc.diff().iloc[:250].std())
        ev = cusum_events(lc, h)
        ev = ev[daily.reindex(ev).notna().to_numpy()]
        width = barrier_vols * daily * np.sqrt(horizon)
        lab = triple_barrier(c, ev, width, horizon)
        if lab.empty:
            continue
        lab["w"] = average_uniqueness(lab, c.index)
        feats = features(df).reindex(lab.index)
        part = pd.concat([lab, feats], axis=1).dropna()
        part["symbol"] = sym
        parts.append(part)
    return pd.concat(parts).sort_index() if parts else pd.DataFrame()


def ml_exam(frames: dict[str, pd.DataFrame], first_year: int | None = None, seed: int = 7,
            **kw) -> list[YearScore]:
    """Walk-forward by calendar year with a purge (see the module doc)."""
    from sklearn.ensemble import RandomForestClassifier

    data = build_events(frames, **kw)
    if data.empty:
        return []
    years = pd.to_datetime(data.index, unit="s").year
    cols = [c for c in data.columns if c not in ("end", "label", "ret", "w", "symbol")]
    out = []
    for year in sorted(set(years)):
        if first_year and year < first_year:
            continue
        start = pd.Timestamp(f"{year}-01-01").timestamp()
        end = pd.Timestamp(f"{year + 1}-01-01").timestamp()
        train = data[(data.index < start) & (data["end"] < start)]     # the purge
        test = data[(data.index >= start) & (data.index < end)]
        if len(train) < 500 or len(test) < 50:
            continue
        model = RandomForestClassifier(n_estimators=200, min_samples_leaf=50, max_features=3,
                                       random_state=seed, n_jobs=-1, class_weight="balanced")
        model.fit(train[cols], train["label"], sample_weight=train["w"])
        pred = model.predict(test[cols])
        majority = train["label"].mode().iloc[0]
        liked = test[pred == 1]
        out.append(YearScore(year, len(test), float((pred == test["label"]).mean()),
                             float((test["label"] == majority).mean()),
                             float(liked["ret"].mean()) if len(liked) else float("nan"),
                             float(test["ret"].mean())))
    return out
