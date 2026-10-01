"""Walk-forward backtests on a synthetic tape written as ReplayMarket CSVs."""
import csv
import math

from cryptoarena.arena.backtest import format_summary, load_tape, run_backtest
from cryptoarena.arena.survival import SurvivalConfig
from cryptoarena.cli import build_agents


def write_tape(directory, bars: int, drift: float = 0.0005) -> None:
    t0 = 1_760_000_000 // 3600 * 3600
    for sym, base in {"BTCUSD": 60_000.0, "ETHUSD": 3_000.0, "SOLUSD": 150.0}.items():
        with (directory / f"{sym}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for i in range(bars):
                o = base * (1 + drift * i + 0.02 * math.sin(i / 40))
                c = base * (1 + drift * (i + 1) + 0.02 * math.sin((i + 1) / 40))
                w.writerow([t0 + i * 3600, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 40.0])


def test_backtest_windows_compare_with_buy_and_hold(tmp_path):
    write_tape(tmp_path, bars=720 + 24 * 10 + 24 * 5 * 2 + 1)   # warm-up + two 10-day windows
    tape = load_tape(tmp_path)
    assert set(tape) == {"BTCUSD", "ETHUSD", "SOLUSD"}
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    report = run_backtest(tape, lambda: build_agents(5.0, False, ""), cfg,
                          days=10, stride_days=5, warmup_bars=720)
    assert len(report.windows) == 3
    for w in report.windows:
        assert w.end_ts - w.start_ts == (24 * 10 - 1) * 3600
        assert w.hold_return > 0                                 # the tape drifts up
        assert set(w.by_strategy) == {a.agent_id for a in build_agents(5.0, False, "")}
        assert w.target_days == 8 * 10                            # every founder, every day
    summary = report.summary()
    assert summary["windows"] == 3 and 0 <= summary["beats_hold"] <= 1
    text = format_summary(summary)
    assert "3 windows" in text and "buy&hold" in text and "trend-1" in text


def test_lineage_counts_for_the_founder(tmp_path):
    """A founder that paid for a child is not 'down' by the child's budget."""
    write_tape(tmp_path, bars=720 + 24 * 20 + 1, drift=0.002)
    tape = load_tape(tmp_path)
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False,
                         clone_at=1.02, min_child_budget=0.05)
    report = run_backtest(tape, lambda: build_agents(5.0, False, ""), cfg,
                          days=20, stride_days=20, warmup_bars=720)
    w = report.windows[0]
    assert w.hires > 0
    founding = 8 * 5.0
    lineage_total = sum(r + 1 for r in w.by_strategy.values()) * 5.0
    assert abs(lineage_total / founding - 1 - w.colony_return) < 1e-9


def test_a_growing_universe_trades_the_coins_that_exist_in_each_window(tmp_path):
    """A coin listed halfway through the tape is absent from the earlier
    windows and present in the later ones; nothing is filled in before its
    listing and a short gap is carried forward."""
    import pandas as pd
    from cryptoarena.arena.backtest import format_by_year, load_tape, window_symbols
    bars = 720 + 24 * 10 + 24 * 5 * 3 + 1
    write_tape(tmp_path, bars=bars, drift=0.001)
    late = pd.read_csv(tmp_path / "SOLUSD.csv")
    half = 200                                       # listed 200 bars in
    late = late.iloc[half:]
    late = late.drop(late.index[3])                   # one missing hour after the listing
    late.to_csv(tmp_path / "SOLUSD.csv", index=False)
    tape = load_tape(tmp_path, align=False)
    n = len(tape["BTCUSD"])
    assert len(tape["SOLUSD"]) == n                   # the union timeline
    assert tape["SOLUSD"]["close"].iloc[:half].isna().all()      # never filled before the listing
    assert tape["SOLUSD"]["close"].iloc[half:].notna().all()     # the gap carried forward
    assert tape["SOLUSD"]["volume"].iloc[half + 3] == 0.0
    assert window_symbols(tape, 0, 100) == ["BTCUSD", "ETHUSD"]
    assert window_symbols(tape, half, 100) == ["BTCUSD", "ETHUSD", "SOLUSD"]
    aligned = load_tape(tmp_path)
    assert len(aligned["BTCUSD"]) == n - half - 1     # the fixed universe keeps only the overlap
    cfg = SurvivalConfig(budget=5.0, seed=1, endogenous=False, learn=False)
    report = run_backtest(tape, lambda: build_agents(5.0, False, ""), cfg,
                          days=10, stride_days=5, warmup_bars=720)
    counts = [w.symbols for w in report.windows]
    assert counts and counts[0] == 2 and counts[-1] == 3 and counts == sorted(counts)
    years = report.by_year()
    assert set(years) == {2025} and years[2025]["windows"] == len(report.windows)
    assert "2025:" in format_by_year(years, ("trend-1",)) and "trend-1" in format_by_year(years, ("trend-1",))
