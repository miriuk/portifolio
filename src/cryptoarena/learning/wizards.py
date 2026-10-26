"""Course 7: the great traders — their paths, their lessons, and their
rules put to the test.

The Market Wizards series by Jack Schwager (Market Wizards 1989, The New
Market Wizards 1992, Stock Market Wizards 2001, Hedge Fund Market Wizards
2012, Unknown Market Wizards 2020) interviews traders who did something
rare for a long time. Michael Marcus, Marty Schwartz and Takashi
Kotegawa ("BNF", not in the series) were asked for by name. The facts
below come from those books as summarised by public sources; figures the
traders never had audited are marked as reported.

Most of what the wizards say is about the trader, not the chart: cut
losses, size small, wait for the best setups, know when you are wrong.
Where a wizard gave a rule mechanical enough to code, it is coded here
and tested the way every course here is: entry at the next open, against
holding the index, and against the same rule with its timing shuffled
(the luck it would have had anyway).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..arena import booksim as bs
from ..portfolio import metrics as m

PROFILES = [
    {"key": "marcus", "name": "Michael Marcus", "books": "Market Wizards (1989)",
     "path": "Começou em 1972 com cerca de US$7 mil em futuros de compensado e quebrou mais de uma vez "
             "no início. Aprendeu gestão de risco com Ed Seykota. Na Commodities Corporation, teria "
             "transformado US$30 mil em US$80 milhões (número divulgado, nunca auditado). Contratou e "
             "formou Bruce Kovner. Morreu em 2023.",
     "lessons": ["corte as perdas cedo", "opere só os melhores setups, não todos",
                 "o trade forte é quando fundamento, gráfico e comportamento do mercado concordam",
                 "um mercado que não cai com notícia ruim está forte"],
     "rule": "risk"},
    {"key": "seykota", "name": "Ed Seykota", "books": "Market Wizards (1989)",
     "path": "Pioneiro dos sistemas de tendência por computador, por volta de 1970, na corretora onde "
             "conheceu Marcus. Os retornos citados variam muito entre as fontes.",
     "lessons": ["quem segue tendência perde na maioria dos trades e vive de cortar perdas e deixar os "
                 "ganhos correrem", "o trader faz parte do sistema: as emoções também operam"],
     "rule": None},
    {"key": "ptj", "name": "Paul Tudor Jones", "books": "Market Wizards (1989)",
     "path": "Fundou a Tudor Investment em 1980 e ficou famoso por ganhar no crash de 1987. A regra "
             "da média de 200 dias vem de uma entrevista a Tony Robbins, não do livro.",
     "lessons": ["defesa antes de ataque", "saia de qualquer coisa que caia abaixo da média de 200 dias",
                 "procure trades em que o ganho possível seja muitas vezes o risco"],
     "rule": "ptj200"},
    {"key": "turtles", "name": "Richard Dennis e as Tartarugas", "books": "Market Wizards (1989); "
     "Way of the Turtle, Curtis Faith (2007)",
     "path": "Em 1983 Dennis apostou com William Eckhardt que trading podia ser ensinado e treinou "
             "novatos com regras fechadas: rompimento de 20 ou 55 dias, saída de 10 ou 20, stop de 2N "
             "e tamanho pela volatilidade.",
     "lessons": ["regras simples, seguidas sempre", "o tamanho da posição pela volatilidade",
                 "aceite muitas perdas pequenas para pegar as poucas tendências grandes"],
     "rule": "turtle"},
    {"key": "hite", "name": "Larry Hite", "books": "Market Wizards (1989)",
     "path": "Cofundou a Mint Investment, gestora de tendência.",
     "lessons": ["nunca arrisque mais de 1% do patrimônio num trade", "sobreviver vem antes de ganhar"],
     "rule": "risk"},
    {"key": "schwartz", "name": "Marty Schwartz", "books": "Market Wizards (1989); Pit Bull (1998)",
     "path": "Analista que só ficou lucrativo de forma consistente quando trocou os fundamentos pela "
             "análise técnica. Venceu o U.S. Investing Championship.",
     "lessons": ["a média exponencial de 10 dias é sinal verde ou vermelho: não compre abaixo dela",
                 "depois de uma perda grande, diminua o tamanho e reconstrua a confiança"],
     "rule": "schwartz10"},
    {"key": "kovner", "name": "Bruce Kovner", "books": "Market Wizards (1989)",
     "path": "Aprendiz de Marcus na Commodities Corporation; fundou a Caxton.",
     "lessons": ["ponha o stop onde o mercado provaria que você está errado",
                 "arrisque pouco em cada trade"],
     "rule": None},
    {"key": "raschke", "name": "Linda Raschke", "books": "The New Market Wizards (1992); "
     "Street Smarts (1995, com Larry Connors)",
     "path": "Trader de curto prazo. O \"Holy Grail\": numa tendência forte (ADX acima de 30), "
             "comprar o recuo até a média de 20.",
     "lessons": ["opere poucos padrões e conheça-os muito bem", "tendência forte recua e continua"],
     "rule": "raschke"},
    {"key": "druckenmiller", "name": "Stanley Druckenmiller", "books": "The New Market Wizards (1992)",
     "path": "Duquesne e Quantum Fund (com Soros).",
     "lessons": ["concentre quando a convicção é alta",
                 "o que importa não é acertar, é quanto ganha quando acerta e quanto perde quando erra"],
     "rule": None},
    {"key": "oneil", "name": "William O'Neil e David Ryan", "books": "Market Wizards (1989)",
     "path": "O'Neil criou o CAN SLIM; Ryan, aluno dele, venceu o U.S. Investing Championship três "
             "vezes. Compram líderes em máxima nova com volume e cortam a perda em 7–8%.",
     "lessons": ["compre força, não barganha", "corte toda perda em 7–8%, sem exceção"],
     "rule": "oneil"},
    {"key": "minervini", "name": "Mark Minervini", "books": "Stock Market Wizards (2001)",
     "path": "Campeão do U.S. Investing Championship de 1997. Só compra ações dentro do seu "
             "\"trend template\" (médias de 50, 150 e 200 em ordem, perto da máxima de 52 semanas).",
     "lessons": ["só ações em estágio 2, a tendência de alta", "stop curto e fixo"],
     "rule": "minervini"},
    {"key": "kotegawa", "name": "Takashi Kotegawa (BNF)", "books": "fora da série; imprensa japonesa",
     "path": "Day e swing trader japonês: comprava papéis que caíam muito abaixo da média de 25 dias "
             "(20–35% em 2001–02, limite que ele mesmo disse ter mudado depois) e vendia na volta à "
             "média. Ficou famoso pelo erro da Mizuho com a J-Com em 8/12/2005. Ele nunca confirmou o "
             "próprio nome nem os números.",
     "lessons": ["compre o pânico, venda a volta ao normal", "segure pouco tempo",
                 "um limiar que funcionou num regime muda no seguinte"],
     "rule": "kotegawa"},
    {"key": "hedge_unknown", "name": "Hedge Fund e Unknown Market Wizards", "books": "2012 e 2020",
     "path": "Os volumes mais novos mostram métodos muito diferentes, de macro a day trade, com a "
             "mesma base: controle de risco, adaptação e disciplina.",
     "lessons": ["não existe um método único", "o controle de risco é o que todos têm em comum"],
     "rule": None},
]


# ------------------------------------------------------------------ panels


def panels(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Dates × symbols matrices of open, high, low, close and volume."""
    cols = ("open", "high", "low", "close", "volume")
    out = {c: pd.DataFrame({s: df.set_index("timestamp")[c] for s, df in frames.items()}).sort_index()
           for c in cols}
    return out


def _cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_down(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


def adx(p: dict[str, pd.DataFrame], n: int = 14) -> pd.DataFrame:
    h, lo, c = p["high"], p["low"], p["close"]
    up, down = h.diff(), -lo.diff()
    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat([h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()]).groupby(level=0).max()
    tr = tr.reindex(h.index)
    atr_ = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atr_
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ------------------------------------------------------------------ the rules
# Each returns (signal, preference, risk rules for booksim.simulate).


def schwartz10(p):
    c = p["close"]
    ema = c.ewm(span=10, adjust=False).mean()
    return (_cross_up(c, ema).astype(int) - _cross_down(c, ema).astype(int)), c.pct_change(252), {}


def ptj200(p):
    c = p["close"]
    sma = c.rolling(200).mean()
    return (_cross_up(c, sma).astype(int) - _cross_down(c, sma).astype(int)), c.pct_change(252), {}


def turtle(p, entry=20, exit_=10):
    c = p["close"]
    hi = p["high"].shift(1).rolling(entry).max()
    lo = p["low"].shift(1).rolling(exit_).min()
    return (c > hi).astype(int) - (c < lo).astype(int), c.pct_change(252), {}


def kotegawa(p, threshold=0.15):
    c = p["close"]
    sma = c.rolling(25).mean()
    dev = c / sma - 1
    buy = (dev <= -threshold) & (dev.shift(1) > -threshold)
    back = c >= sma
    return buy.astype(int) - back.astype(int), -dev, {"max_hold": 10}


def minervini(p):
    c = p["close"]
    s50, s150, s200 = (c.rolling(n).mean() for n in (50, 150, 200))
    lo52, hi52 = p["low"].rolling(252).min(), p["high"].rolling(252).max()
    ok = (c > s150) & (c > s200) & (s150 > s200) & (s200 > s200.shift(21)) & (s50 > s150) & \
        (c > s50) & (c >= 1.3 * lo52) & (c >= 0.75 * hi52)
    enter = ok & ~ok.shift(1, fill_value=False)
    return enter.astype(int) - (c < s50).astype(int), c.pct_change(252), {"stop_loss": 0.08}


def oneil(p):
    c, v = p["close"], p["volume"]
    new_high = c >= p["high"].rolling(252).max()
    heavy = v > 1.4 * v.shift(1).rolling(50).mean()
    return (new_high & heavy).astype(int), c.pct_change(252), {"stop_loss": 0.08, "take_profit": 0.25}


def raschke(p):
    c, lo = p["close"], p["low"]
    ema = c.ewm(span=20, adjust=False).mean()
    a = adx(p)
    up = (a > 30) & (a > a.shift(1)) & (c.shift(1) > ema.shift(1))
    touch = (lo <= ema) & (c > ema)
    target = c > p["high"].shift(1).rolling(20).max()
    return (up & touch).astype(int) - target.astype(int), a, {"max_hold": 10, "stop_loss": 0.05}


RULES = {
    "schwartz10": ("Marty Schwartz: média exponencial de 10 dias", schwartz10),
    "ptj200": ("Paul Tudor Jones: média de 200 dias", ptj200),
    "turtle20": ("Tartarugas, sistema 1: rompe 20, sai em 10", lambda p: turtle(p, 20, 10)),
    "turtle55": ("Tartarugas, sistema 2: rompe 55, sai em 20", lambda p: turtle(p, 55, 20)),
    "kotegawa10": ("Kotegawa: 10% abaixo da média de 25", lambda p: kotegawa(p, 0.10)),
    "kotegawa15": ("Kotegawa: 15% abaixo da média de 25", lambda p: kotegawa(p, 0.15)),
    "kotegawa20": ("Kotegawa: 20% abaixo da média de 25", lambda p: kotegawa(p, 0.20)),
    "minervini": ("Minervini: trend template, stop de 8%", minervini),
    "oneil": ("O'Neil/Ryan: máxima de 52 semanas com volume", oneil),
    "raschke": ("Raschke: Holy Grail (ADX > 30, recuo à média de 20)", raschke),
}


# ------------------------------------------------------------------ the exams


@dataclass
class Score:
    rule: str
    where: str
    cagr: float
    sharpe: float
    max_drawdown: float
    hold_cagr: float
    hold_sharpe: float
    hold_drawdown: float
    in_market: float = float("nan")
    luck_pct: float = float("nan")      # the share of entry-shuffled runs the real rule beats
    universe_cagr: float = float("nan")  # the traded universe held in equal weights


def _shuffled_entries(sig: pd.DataFrame, rng) -> pd.DataFrame:
    """The same number of entries per name on random days, drawn only from
    the days the rule's own exit is not already telling it to leave (so a
    random entry can live as long as a real one would); the exits stay
    the rule's. What is left of the result is the entry timing."""
    entries, exits = (sig > 0).to_numpy(), (sig < 0).to_numpy()
    moved = np.zeros_like(entries)
    for j in range(entries.shape[1]):
        open_days = np.where(~exits[:, j])[0]
        k = int(entries[:, j].sum())
        if k and len(open_days):
            moved[rng.choice(open_days, size=min(k, len(open_days)), replace=False), j] = True
    return pd.DataFrame(moved.astype(int) - exits.astype(int), index=sig.index, columns=sig.columns)


def _years(idx) -> float:
    return (idx[-1] - idx[0]) / (365.25 * 86400)


def timing_exam(p: dict[str, pd.DataFrame], symbol: str, rule: str, slippage: float = 0.0005,
                shuffles: int = 50, seed: int = 0) -> Score:
    """One asset, in or out by the rule, filled at the next open, against
    holding it and against the rule with its entry days shuffled."""
    sub = {k: v[[symbol]].dropna() for k, v in p.items()}
    idx = sub["close"].dropna().index
    sub = {k: v.reindex(idx) for k, v in sub.items()}
    sig, pref, risk = RULES[rule][1](sub)
    start = idx[260] if len(idx) > 300 else idx[0]          # every indicator has warmed up
    keep = idx >= start
    sl = {k: v[keep] for k, v in sub.items()}
    kw = dict(max_positions=1, slippage=slippage, exec_prices=sl["open"].shift(-1), **risk)
    pr = pref[keep].fillna(0)
    eq = bs.simulate(sl["close"], sig[keep], pr, **kw)
    hold = sl["close"][symbol]
    held = (sig[keep][symbol].replace(0, np.nan).ffill().fillna(-1) > 0).mean()
    rng = np.random.default_rng(seed)
    real = m.cagr(eq)
    runs = [m.cagr(bs.simulate(sl["close"], _shuffled_entries(sig[keep], rng), pr, **kw))
            for _ in range(shuffles)]
    return Score(rule, symbol, real, m.sharpe(eq), m.max_drawdown(eq, log=False),
                 m.cagr(hold), m.sharpe(hold), m.max_drawdown(hold, log=False), float(held),
                 float((np.array(runs) < real).mean()))


def picking_exam(p: dict[str, pd.DataFrame], rule: str, benchmark: pd.Series, where: str,
                 max_positions: int = 10, shuffles: int = 30, seed: int = 0,
                 slippage: float = 0.0005) -> Score:
    """Up to `max_positions` names at a time by the rule, against holding
    the benchmark; and against the same rule with each name's signal days
    shuffled in time (the same number of entries and exits, no timing)."""
    sig, pref, risk = RULES[rule][1](p)
    start = p["close"].index[260]
    keep = p["close"].index >= start
    px, ex = p["close"][keep], p["open"].shift(-1)[keep]
    sig, pref = sig[keep], pref[keep].fillna(-1e9)
    eq = bs.simulate(px, sig, pref, max_positions=max_positions, slippage=slippage, exec_prices=ex, **risk)
    b = benchmark.reindex(px.index).ffill()
    real = bs.excess_cagr(eq, b)
    rng = np.random.default_rng(seed)
    runs = [bs.excess_cagr(bs.simulate(px, _shuffled_entries(sig, rng), pref,
                                       max_positions=max_positions, slippage=slippage,
                                       exec_prices=ex, **risk), b) for _ in range(shuffles)]
    universe = (1 + px.pct_change().mean(axis=1).fillna(0)).cumprod()
    return Score(rule, where, m.cagr(eq), m.sharpe(eq), m.max_drawdown(eq, log=False), m.cagr(b),
                 m.sharpe(b), m.max_drawdown(b, log=False),
                 luck_pct=float((np.array(runs) < real).mean()), universe_cagr=m.cagr(universe))


def risk_exam(p: dict[str, pd.DataFrame], benchmark: pd.Series, runs: int = 20, rate: float = 0.02,
              seed: int = 0, slippage: float = 0.0005) -> dict[str, np.ndarray]:
    """Marcus, Seykota, Hite: is "cut losses, let profits run" worth
    anything on its own? The same random entries, three ways: held 20
    days; with an 8% stop and a 15% trailing stop (no time limit); and
    with only the stop. Returns each variant's excess CAGR over the runs."""
    start = p["close"].index[260]
    keep = p["close"].index >= start
    px, ex = p["close"][keep], p["open"].shift(-1)[keep]
    b = benchmark.reindex(px.index).ffill()
    rng = np.random.default_rng(seed)
    variants = {"segurar 20 dias": {"max_hold": 20},
                "stop 8% + trailing 15%": {"stop_loss": 0.08, "trail": 0.15},
                "só stop 8%, 60 dias": {"stop_loss": 0.08, "max_hold": 60}}
    out = {k: [] for k in variants}
    for _ in range(runs):
        sig = pd.DataFrame((rng.random(px.shape) < rate).astype(int), index=px.index, columns=px.columns)
        pref = pd.DataFrame(rng.random(px.shape), index=px.index, columns=px.columns)
        for name, risk in variants.items():
            eq = bs.simulate(px, sig, pref, max_positions=10, slippage=slippage, exec_prices=ex, **risk)
            out[name].append(bs.excess_cagr(eq, b))
    return {k: np.array(v) for k, v in out.items()}
