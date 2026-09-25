"""Microsoft Qlib's stock-ranking pipeline on the world universe.

Qlib (github.com/microsoft/qlib) does not time the market: every day it
ranks the stocks of a universe against each other with 158 technical
features (Alpha158), and a portfolio holds the top `topk`, swapping out at
most `n_drop` a day (TopkDropoutStrategy). The models and their parameters
are copied from Qlib's own benchmark configs (examples/benchmarks/*/
workflow_config_*_Alpha158.yaml), where on China's CSI300 (tested
2017-2020) they reach an IC of 0.04-0.05 and 7-12% a year over the index.

Here the universe is the US large caps or the world index ETFs of
`market/universe.py`, retrained every year on an expanding window:
test year Y trains on everything up to Y-2, validates on Y-1 (early
stopping only) and predicts Y. Baselines through the same portfolio and
costs: 12-1 month momentum (the strongest single signal in the academic
literature), and the benchmark and the equal-weight universe held.

    write_provider({"stocks": "data/global/stocks", "etf": "data/global/etf"}, "qlib_data")
    report = run("qlib_data", universe="stocks", benchmark="SPY")
"""
from __future__ import annotations

import statistics
from pathlib import Path

import numpy as np
import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume", "vwap", "factor", "change")

# Qlib's published Alpha158 configs, verbatim (num_threads lowered to the
# machine: it changes speed, not results).
MODELS = {
    "LightGBM": ("qlib.contrib.model.gbdt", "LGBModel", dict(
        loss="mse", colsample_bytree=0.8879, learning_rate=0.2, subsample=0.8789,
        lambda_l1=205.6999, lambda_l2=580.9768, max_depth=8, num_leaves=210, num_threads=4)),
    "DoubleEnsemble": ("qlib.contrib.model.double_ensemble", "DEnsembleModel", dict(
        base_model="gbm", loss="mse", num_models=3, enable_sr=True, enable_fs=True, alpha1=1,
        alpha2=1, bins_sr=10, bins_fs=5, decay=0.5, sample_ratios=[0.8, 0.7, 0.6, 0.5, 0.4],
        sub_weights=[1, 1, 1], epochs=28, colsample_bytree=0.8879, learning_rate=0.2,
        subsample=0.8789, lambda_l1=205.6999, lambda_l2=580.9768, max_depth=8, num_leaves=210,
        num_threads=4, verbosity=-1)),
    "XGBoost": ("qlib.contrib.model.xgboost", "XGBModel", dict(
        eval_metric="rmse", colsample_bytree=0.8879, eta=0.0421, max_depth=8, n_estimators=647,
        subsample=0.8789, nthread=4)),
    "Linear": ("qlib.contrib.model.linear", "LinearModel", dict(estimator="ols")),
}


# ------------------------------------------------------------------ data
def write_provider(csv_dirs: dict[str, str | Path], out: str | Path) -> dict[str, list[str]]:
    """Daily CSVs -> Qlib's binary layout: calendars/day.txt, one
    instruments/<group>.txt per directory (plus all.txt), and
    features/<symbol>/<field>.day.bin (little-endian float32, the first
    value being the symbol's first index in the calendar). `vwap` is
    approximated by the typical price (high + low + close) / 3; prices
    are split-adjusted already, so `factor` is 1."""
    out = Path(out)
    frames: dict[str, pd.DataFrame] = {}
    groups: dict[str, list[str]] = {}
    for group, d in csv_dirs.items():
        for path in sorted(Path(d).glob("*.csv")):
            df = pd.read_csv(path).sort_values("timestamp").drop_duplicates("timestamp")
            df["date"] = pd.to_datetime(df["timestamp"], unit="s").dt.normalize()
            frames[path.stem.upper()] = df.set_index("date")
            groups.setdefault(group, []).append(path.stem.upper())
    calendar = sorted(set().union(*(df.index for df in frames.values())))
    pos = {d: i for i, d in enumerate(calendar)}
    (out / "calendars").mkdir(parents=True, exist_ok=True)
    (out / "calendars" / "day.txt").write_text("\n".join(d.strftime("%Y-%m-%d") for d in calendar) + "\n")
    spans = {}
    for sym, df in frames.items():
        first, last = df.index[0], df.index[-1]
        idx = pd.DatetimeIndex(calendar[pos[first]:pos[last] + 1])
        f = df.reindex(idx)
        f["vwap"] = (f["high"] + f["low"] + f["close"]) / 3
        f["factor"] = 1.0
        f["change"] = f["close"] / f["close"].shift(1) - 1
        d = out / "features" / sym.lower()
        d.mkdir(parents=True, exist_ok=True)
        for field in FIELDS:
            np.hstack([[pos[first]], f[field].to_numpy(float)]).astype("<f4").tofile(
                d / f"{field}.day.bin")
        spans[sym] = (first, last)
    (out / "instruments").mkdir(parents=True, exist_ok=True)
    for name, syms in {**groups, "all": list(frames)}.items():
        (out / "instruments" / f"{name}.txt").write_text("".join(
            f"{s}\t{spans[s][0]:%Y-%m-%d}\t{spans[s][1]:%Y-%m-%d}\n" for s in syms))
    return groups


# ------------------------------------------------------------------ run
def _init(provider: str | Path) -> None:
    import qlib
    from qlib.constant import REG_US
    qlib.init(provider_uri=str(Path(provider).resolve()), region=REG_US, kernels=1)


def _dataset(universe: str, start: str, train_end: str, valid: tuple[str, str],
             test: tuple[str, str]):
    from qlib.contrib.data.handler import Alpha158
    from qlib.data.dataset import DatasetH
    handler = Alpha158(
        instruments=universe, start_time=start, end_time=test[1],
        fit_start_time=start, fit_end_time=train_end,
        infer_processors=[{"class": "RobustZScoreNorm",
                           "kwargs": {"fields_group": "feature", "clip_outlier": True}},
                          {"class": "Fillna", "kwargs": {"fields_group": "feature"}}],
        learn_processors=[{"class": "DropnaLabel"},
                          {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}}])
    return DatasetH(handler, segments={"train": (start, train_end), "valid": valid, "test": test})


def _model(name: str):
    import importlib
    module, cls, kwargs = MODELS[name]
    return getattr(importlib.import_module(module), cls)(**kwargs)


def _momentum(universe: str, start: str, end: str) -> pd.Series:
    """12-1 month momentum: the return from 252 to 21 sessions ago."""
    from qlib.data import D
    df = D.features(D.instruments(universe), ["Ref($close, 21) / Ref($close, 252) - 1"],
                    start_time=start, end_time=end)
    s = df.iloc[:, 0].dropna()
    s.index = s.index.swaplevel()                 # (datetime, instrument), as model predictions
    return s.sort_index()


def _label(universe: str, start: str, end: str) -> pd.Series:
    from qlib.data import D
    df = D.features(D.instruments(universe), ["Ref($close, -2) / Ref($close, -1) - 1"],
                    start_time=start, end_time=end)
    s = df.iloc[:, 0]
    s.index = s.index.swaplevel()
    return s.sort_index()


def _backtest(signal: pd.Series, start: str, end: str, benchmark: str, topk: int, n_drop: int,
              cost: float) -> pd.DataFrame:
    from qlib.contrib.evaluate import backtest_daily
    from qlib.contrib.strategy import TopkDropoutStrategy
    strategy = TopkDropoutStrategy(signal=signal, topk=topk, n_drop=n_drop)
    report, _ = backtest_daily(start_time=start, end_time=end, strategy=strategy, account=1e7,
                               benchmark=benchmark,
                               exchange_kwargs={"freq": "day", "limit_threshold": None,
                                                "deal_price": "close", "open_cost": cost,
                                                "close_cost": cost, "min_cost": 0})
    return report


def _curve_stats(daily: pd.Series) -> dict:
    daily = daily.dropna()
    curve = (1 + daily).cumprod()
    years = len(daily) / 252
    return {"cagr": float(curve.iloc[-1] ** (1 / years) - 1) if years > 0 else float("nan"),
            "max_drawdown": float((1 - curve / curve.cummax()).max()),
            "vol": float(daily.std() * 252 ** 0.5)}


def run(provider: str | Path, universe: str = "stocks", benchmark: str = "SPY",
        models: list[str] | None = None, first_test_year: int = 2020, last_test_year: int = 2026,
        topk: int = 10, n_drop: int = 2, cost: float = 0.0005, verbose: bool = True) -> dict:
    from qlib.contrib.eva.alpha import calc_ic
    from qlib.data import D
    _init(provider)
    models = models or list(MODELS)
    cal = D.calendar(freq="day")
    start = str(cal[0].date())
    end = str(cal[-1].date())
    preds: dict[str, list[pd.Series]] = {m: [] for m in models}
    for y in range(first_test_year, last_test_year + 1):
        test = (f"{y}-01-01", min(f"{y}-12-31", end))
        if pd.Timestamp(test[0]) > cal[-1]:
            break
        # the label looks two sessions ahead: stop validation a week early
        valid = (f"{y - 1}-01-01", f"{y - 1}-12-24")
        train_end = f"{y - 2}-12-24"
        ds = _dataset(universe, start, train_end, valid, test)
        for m in models:
            model = _model(m)
            model.fit(ds)
            p = model.predict(ds, segment="test")
            preds[m].append(p if isinstance(p, pd.Series) else p.iloc[:, 0])
            if verbose:
                print(f"  {y} {m}: {len(p)} predictions", flush=True)
    # Qlib's backtest needs the session after the last one it trades
    test_start, test_end = f"{first_test_year}-01-01", str(cal[-2].date())
    signals = {m: pd.concat(v).sort_index() for m, v in preds.items() if v}
    signals["momentum 12-1"] = _momentum(universe, test_start, test_end)
    label = _label(universe, test_start, test_end)
    out: dict = {"universe": universe, "benchmark": benchmark, "topk": topk, "n_drop": n_drop,
                 "cost": cost, "test": [test_start, test_end], "rows": {}}
    bench_ret = None
    for name, sig in signals.items():
        sig = sig[sig.index.get_level_values(0) >= pd.Timestamp(test_start)]
        ic, ric = calc_ic(sig, label.reindex(sig.index))
        report = _backtest(sig, test_start, test_end, benchmark, topk, n_drop, cost)
        net = report["return"] - report["cost"]
        bench_ret = report["bench"]
        years = net.groupby(net.index.year)
        out["rows"][name] = {
            "ic": float(ic.mean()), "rank_ic": float(ric.mean()),
            "icir": float(ic.mean() / ic.std()) if ic.std() > 0 else float("nan"),
            **_curve_stats(net),
            "excess": float(net.mean() * 252 - bench_ret.mean() * 252),
            "turnover": float(report["turnover"].mean()),
            "by_year": {int(k): float((1 + v).prod() - 1) for k, v in years},
        }
        if verbose:
            r = out["rows"][name]
            print(f"  {name}: IC {r['ic']:+.4f} rank IC {r['rank_ic']:+.4f} "
                  f"CAGR {r['cagr']:+.1%} max fall {r['max_drawdown']:.0%}", flush=True)
    # the benchmark and the equal-weight universe, held (no trading costs)
    out["rows"][f"hold {benchmark}"] = {**_curve_stats(bench_ret), "excess": 0.0,
                                        "by_year": {int(k): float((1 + v).prod() - 1)
                                                    for k, v in bench_ret.groupby(bench_ret.index.year)}}
    closes = D.features(D.instruments(universe), ["$close"], start_time=test_start, end_time=test_end)
    ew = closes.iloc[:, 0].unstack(level=0).pct_change().mean(axis=1).reindex(bench_ret.index)
    out["rows"]["equal-weight universe"] = {**_curve_stats(ew),
                                            "excess": float(ew.mean() * 252 - bench_ret.mean() * 252),
                                            "by_year": {int(k): float((1 + v).prod() - 1)
                                                        for k, v in ew.groupby(ew.index.year)}}
    return out


def format_report(rep: dict) -> str:
    lines = [f"{rep['universe']}: top {rep['topk']} (swap {rep['n_drop']}/day), "
             f"{rep['cost']:.2%} per side, test {rep['test'][0]} to {rep['test'][1]}, "
             f"benchmark {rep['benchmark']}",
             f"{'signal':<22} {'IC':>7} {'rank IC':>8} {'CAGR':>7} {'vs bench':>9} "
             f"{'max fall':>8} {'turnover':>8}"]
    for name, r in rep["rows"].items():
        ic = f"{r['ic']:+.4f}" if "ic" in r else "—"
        ric = f"{r['rank_ic']:+.4f}" if "rank_ic" in r else "—"
        to = f"{r['turnover']:.1%}" if "turnover" in r else "—"
        lines.append(f"{name:<22} {ic:>7} {ric:>8} {r['cagr']:>+7.1%} {r['excess']:>+9.1%} "
                     f"{r['max_drawdown']:>8.0%} {to:>8}")
    years = sorted({y for r in rep["rows"].values() for y in r.get("by_year", {})})
    lines.append("")
    lines.append(f"{'by year':<22} " + " ".join(f"{y:>7}" for y in years))
    for name, r in rep["rows"].items():
        lines.append(f"{name:<22} " + " ".join(f"{r['by_year'].get(y, float('nan')):>+7.1%}"
                                               for y in years))
    return "\n".join(lines)
