"""Kronos in the forecast bench: three open sizes, a pinned install, and
the wrapper turning sampled candles into a log-return forecast."""
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cryptoarena.cli import FORECASTERS, _forecasters
from cryptoarena.forecast.models import KRONOS_SIZES, KronosModel

ROOT = Path(__file__).resolve().parents[1]


def test_the_three_open_sizes_compare_on_equal_terms():
    made = {name: _forecasters()[name](True) for name in ("kronos-mini", "kronos", "kronos-base")}
    assert {n for n in made} <= set(FORECASTERS)
    assert (made["kronos-mini"].model_id, made["kronos-mini"].tokenizer_id) == KRONOS_SIZES["mini"]
    assert made["kronos-mini"].tokenizer_id.endswith("Tokenizer-2k")      # mini has its own
    assert made["kronos"].model_id == "NeoQuasar/Kronos-small"           # the name kept from before
    assert made["kronos-base"].model_id == "NeoQuasar/Kronos-base"
    assert [m.name for m in made.values()] == ["Kronos mini", "Kronos small", "Kronos base"]
    assert {(m.context_days, m.samples) for m in made.values()} == {(256, 3)}


def _contexts(lengths):
    out = []
    for n in lengths:
        ts = pd.Series(pd.bdate_range("2025-01-01", periods=n))
        close = np.linspace(100, 110, n)
        out.append(pd.DataFrame({"timestamps": ts, "open": close, "high": close * 1.01,
                                 "low": close * 0.99, "close": close, "volume": 1.0}))
    return out


def test_the_forecast_is_the_log_return_to_the_last_sampled_close(monkeypatch):
    calls = []

    class Fake:
        def predict_batch(self, dfs, xts, yts, pred_len, **kw):
            calls.append((len(dfs), len(dfs[0]), pred_len, kw["sample_count"]))
            assert all(len(y) == pred_len for y in yts)
            assert all(y.iloc[0] > x.iloc[-1] for x, y in zip(xts, yts))   # the future, after the past
            return [pd.DataFrame({"close": [df["close"].iloc[-1] * 1.02] * pred_len}) for df in dfs]

    model = KronosModel(*KRONOS_SIZES["small"], context_days=256, samples=3)
    model._predictor = Fake()
    monkeypatch.setattr(KronosModel, "_seed", lambda self: None)
    out = model.predict(_contexts([30, 30, 20]), horizon=5)
    assert out == pytest.approx([np.log(1.02)] * 3)
    assert sorted(calls) == [(1, 20, 5, 3), (2, 30, 5, 3)]   # one batch per context length


def test_the_install_script_pins_a_commit():
    text = (ROOT / "scripts" / "install_kronos.sh").read_text()
    ref = next(line for line in text.splitlines() if line.startswith("KRONOS_REF="))
    sha = ref.split(":-", 1)[1].split("}", 1)[0]
    assert len(sha) == 40 and int(sha, 16) >= 0
    assert "Kronos/" in (ROOT / ".gitignore").read_text()                  # never committed here


def test_against_the_real_kronos_code_with_random_weights(monkeypatch):
    torch = pytest.importorskip("torch")
    path = os.environ.get("KRONOS_PATH", str(ROOT / "Kronos"))
    if not (Path(path) / "model" / "kronos.py").exists():
        pytest.skip("Kronos code not installed (scripts/install_kronos.sh)")
    monkeypatch.syspath_prepend(path)
    from model import Kronos, KronosPredictor, KronosTokenizer
    torch.manual_seed(0)
    tok = KronosTokenizer(d_in=6, d_model=32, n_heads=2, ff_dim=64, n_enc_layers=1, n_dec_layers=1,
                          ffn_dropout_p=0.0, attn_dropout_p=0.0, resid_dropout_p=0.0, s1_bits=4,
                          s2_bits=4, beta=0.05, gamma0=1.0, gamma=1.1, zeta=0.05, group_size=4)
    mdl = Kronos(s1_bits=4, s2_bits=4, n_layers=1, d_model=32, n_heads=2, ff_dim=64,
                 ffn_dropout_p=0.0, attn_dropout_p=0.0, resid_dropout_p=0.0, token_dropout_p=0.0,
                 learn_te=True)
    model = KronosModel(*KRONOS_SIZES["small"], context_days=64, samples=2)
    model._predictor = KronosPredictor(mdl, tok, device="cpu", max_context=64)
    out = model.predict(_contexts([64, 64]), horizon=5)
    assert out.shape == (2,) and np.isfinite(out).all()


def test_the_bench_workflow_installs_the_pinned_code():
    wf = (ROOT / ".github" / "workflows" / "forecast-bench.yml").read_text()
    assert "scripts/install_kronos.sh" in wf and "kronos-base" in wf
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install_kronos.sh")]).returncode == 0
