"""Our daily bars in Qlib's binary layout."""
import numpy as np
import pandas as pd
import pytest

from cryptoarena.forecast.qlib_bench import FIELDS, MODELS, write_provider


def bars(path, days, closes):
    ts = (days.astype("int64") // 10**9)
    c = np.asarray(closes, float)
    pd.DataFrame({"timestamp": ts, "open": c, "high": c * 1.02, "low": c * 0.98, "close": c,
                  "volume": 1e6}).to_csv(path, index=False)


def test_the_provider_layout_is_what_qlib_reads(tmp_path):
    days = pd.bdate_range("2024-01-01", periods=10)
    (tmp_path / "stocks").mkdir()
    (tmp_path / "etf").mkdir()
    bars(tmp_path / "stocks" / "AAA.csv", days, np.arange(100, 110))
    bars(tmp_path / "stocks" / "BBB.csv", days[3:], np.arange(50, 57))     # listed later
    bars(tmp_path / "etf" / "SPY.csv", days, np.arange(400, 410))
    out = tmp_path / "q"
    groups = write_provider({"stocks": tmp_path / "stocks", "etf": tmp_path / "etf"}, out)
    assert groups == {"stocks": ["AAA", "BBB"], "etf": ["SPY"]}
    cal = (out / "calendars" / "day.txt").read_text().split()
    assert cal[0] == "2024-01-01" and len(cal) == 10
    inst = (out / "instruments" / "stocks.txt").read_text().splitlines()
    assert inst[1] == "BBB\t2024-01-04\t2024-01-12"
    assert (out / "instruments" / "all.txt").read_text().count("\n") == 3
    for f in FIELDS:
        assert (out / "features" / "bbb" / f"{f}.day.bin").exists()
    close = np.fromfile(out / "features" / "bbb" / "close.day.bin", dtype="<f4")
    assert close[0] == 3 and close[1:].tolist() == list(range(50, 57))    # start index, then values
    vwap = np.fromfile(out / "features" / "aaa" / "vwap.day.bin", dtype="<f4")
    assert vwap[1] == pytest.approx(100.0)                                # (h + l + c) / 3
    change = np.fromfile(out / "features" / "aaa" / "change.day.bin", dtype="<f4")
    assert np.isnan(change[1]) and change[2] == pytest.approx(0.01)


def test_the_models_are_qlibs_published_configs():
    assert set(MODELS) == {"LightGBM", "DoubleEnsemble", "XGBoost", "Linear"}
    lgb = MODELS["LightGBM"][2]
    assert lgb["learning_rate"] == 0.2 and lgb["num_leaves"] == 210 and lgb["lambda_l2"] == 580.9768
    assert MODELS["XGBoost"][2]["n_estimators"] == 647
    assert MODELS["Linear"][2] == {"estimator": "ols"}
