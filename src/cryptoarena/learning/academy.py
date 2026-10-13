"""The academy: courses for the agents, from *Algorithmic Trading with
Python* (Chris Conlan, 2020; github.com/chrisconlan/algorithmic-trading-
with-python). The book's code is freeware for personal use only, so
nothing of it is copied: each course is the chapter's idea written again
here, and each ends in an exam on real bars.

| course | chapter | what the agents learn                    | where it lives            |
|--------|---------|------------------------------------------|---------------------------|
| 1      | 2       | measuring a strategy (Sharpe, Sortino, …) | portfolio/metrics.py      |
| 2      | 3       | indicators: MACD, Bollinger, Chaikin      | agents/rules.py (3 agents)|
| 3      | 4       | a portfolio simulator with slots          | arena/booksim.py          |
| 4      | 5       | not fooling yourself: noise and bootstrap | arena/booksim.py          |
| 5      | 6–7     | financial machine learning                | forecast/events.py        |

The point is not a fortune: it is that every agent can say how it is
doing, knows the classic tools, and can tell skill from luck.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

COURSES = {
    1: ("Medir desempenho", "capítulo 2",
        "CAGR, volatilidade, Sharpe, Sortino, queda máxima, Calmar, pure profit score, alfa de Jensen"),
    2: ("Indicadores e sinais", "capítulo 3",
        "MACD, Bandas de Bollinger e Chaikin Money Flow — três especialistas formados"),
    3: ("Simular uma carteira", "capítulo 4",
        "vagas limitadas, preferência entre candidatos, slippage e taxa fixa"),
    4: ("Não se enganar", "capítulo 5",
        "teste de ruído branco e de bootstrap: habilidade ou sorte?"),
    5: ("Aprendizado de máquina financeiro", "capítulos 6 e 7",
        "filtro CUSUM, rótulos de barreira tripla, peso por exclusividade, walk-forward com purga"),
    6: ("Análise técnica", "21 técnicas de mercado",
        "Fibonacci, rompimentos, reversões, Elliott, FVG, candles, Heikin-Ashi, lua, Renko, "
        "harmônicos, suporte e resistência, suporte dinâmico, LTA/LTB, Gann, IFR, divergência, "
        "volume, oferta e demanda, estrutura, BOS, CHoCH — a confiança de cada uma vem da prova"),
}


# ------------------------------------------------------------------ course 1
def colony_report_cards(frames: dict[str, pd.DataFrame], make_founders, cfg, warmup_bars: int = 250,
                        benchmark: str = "SPY") -> pd.DataFrame:
    """One continuous colony over the whole tape, then every strategy's
    report card (founder and its interns together), the colony's, and the
    benchmark's own, with beta and Jensen's alpha against it."""
    from ..arena.backtest import TapeSlice
    from ..arena.survival import SurvivalConfig, run_survival
    from ..portfolio.metrics import report_card
    from ..world.personas import display

    from .memory import TradeJournal

    n = len(next(iter(frames.values())))
    days = (n - warmup_bars - 1) // cfg.steps_per_day
    run_cfg = SurvivalConfig(**{**cfg.__dict__, "days": days, "warmup_bars": warmup_bars})
    journal = TradeJournal(":memory:")
    try:
        run_survival(make_founders(), journal, run_cfg, verbose=False,
                     market=TapeSlice(frames, 0, warmup_bars + days * cfg.steps_per_day))
        eq = pd.read_sql("SELECT agent_id, episode, step, equity FROM equity_snapshots",
                         journal._conn)
    finally:
        journal.close()
    last_step = eq.groupby("episode")["step"].transform("max")
    eq = eq[eq["step"] == last_step]
    ts = frames[next(iter(frames))]["timestamp"].to_numpy()
    eq["ts"] = [int(ts[warmup_bars + (d - 1) * cfg.steps_per_day + s]) for d, s in
                zip(eq["episode"], eq["step"])]
    # a founder's own curve (an intern's money arrives in steps, not as returns)
    founders = {a.agent_id for a in make_founders()}
    mine = eq[eq["agent_id"].isin(founders)].copy()
    mine["who"] = [display(a) for a in mine["agent_id"]]
    bench = frames[benchmark].set_index("timestamp")["close"] if benchmark in frames else None
    rows = []
    for name, g in list(mine.groupby("who", sort=False)) + [("🏢 colônia", eq)]:
        curve = g.groupby("ts")["equity"].sum().sort_index()
        if len(curve) < 30:
            continue                                    # an intern hired at the very end
        b = bench.reindex(curve.index) if bench is not None else None
        rows.append({"who": name, **report_card(curve, b)})
    if bench is not None:
        b = bench.reindex(eq["ts"].drop_duplicates().sort_values()).dropna()
        rows.append({"who": f"segurar {benchmark}", **report_card(b, b)})
    return pd.DataFrame(rows).set_index("who")


def format_cards(cards: pd.DataFrame) -> str:
    cols = [("cagr", "CAGR", "{:+.1%}"), ("volatility", "vol.", "{:.1%}"),
            ("sharpe", "Sharpe", "{:+.2f}"), ("sortino", "Sortino", "{:+.2f}"),
            ("max_drawdown", "queda máx.", "{:.1%}"), ("calmar", "Calmar", "{:+.2f}"),
            ("pure_profit", "pure profit", "{:+.1%}"), ("beta", "beta", "{:.2f}"),
            ("alpha", "alfa/ano", "{:+.1%}")]
    lines = [f"{'':<22}" + "".join(f"{h:>12}" for _, h, _ in cols)]
    for who, r in cards.iterrows():
        lines.append(f"{who:<22}" + "".join(
            f"{(f.format(r[k]) if k in r and r[k] == r[k] else '—'):>12}" for k, _, f in cols))
    return "\n".join(lines)


# ------------------------------------------------------------------ course 2
GRADUATES = {"macd": ("MacdAgent", {"fast": 5, "slow": 34}),
             "bollinger": ("BollingerAgent", {"n": 20}),
             "chaikin": ("ChaikinAgent", {"n": 20})}
DAILY = {"cooldown": 3, "max_exposure": 1.0}


def graduate(kind: str, cash: float, daily: bool = True):
    from ..agents import rules
    cls, params = GRADUATES[kind]
    return getattr(rules, cls)(f"{kind}-1", cash, params={**DAILY, **params} if daily else {})


@dataclass
class ExamRow:
    who: str
    universe: str
    windows: int
    mean: float
    bench: float
    t: float


def graduate_exam(universes: dict[str, tuple[dict, dict]], cfg, days: int = 60,
                  stride: int = 20, warmup: int = 250, benchmark: str = "SPY") -> list[ExamRow]:
    """Each graduate alone, in each universe, against the benchmark over
    the same windows. `universes`: name -> (tape, run_backtest kwargs)."""
    import math
    import statistics

    from ..arena.backtest import run_backtest
    from ..world.personas import display
    out = []
    for kind in GRADUATES:
        for uname, (tape, kw) in universes.items():
            rep = run_backtest(tape, lambda: [graduate(kind, cfg.budget)], cfg, days=days,
                               stride_days=stride, warmup_bars=warmup, benchmark=benchmark, **kw)
            ws = [w for w in rep.windows if w.bench_return is not None]
            d = [w.colony_return - w.bench_return for w in ws]
            sd = statistics.pstdev(d) if len(d) > 1 else 0.0
            overlap = max(1, days // stride)
            t = statistics.fmean(d) / (sd / math.sqrt(len(d) / overlap)) if sd else float("nan")
            out.append(ExamRow(display(f"{kind}-1"), uname, len(ws),
                               statistics.fmean(w.colony_return for w in ws),
                               statistics.fmean(w.bench_return for w in ws), t))
    return out


def format_exam(rows: list[ExamRow]) -> str:
    lines = [f"{'formando':<22}{'universo':<14}{'janelas':>8}{'média':>9}{'índice':>9}{'dif.':>9}{'t':>6}"]
    for r in rows:
        lines.append(f"{r.who:<22}{r.universe:<14}{r.windows:>8}{r.mean:>+9.2%}{r.bench:>+9.2%}"
                     f"{(r.mean - r.bench) * 100:>+8.2f}p{r.t:>+6.1f}")
    return "\n".join(lines)


def price_matrix(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Dates × symbols of closes (the shape the book's simulator reads)."""
    return pd.DataFrame({s: df.set_index("timestamp")["close"] for s, df in frames.items()}).sort_index()
