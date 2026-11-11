"""Course 1 of the academy: how to measure a strategy.

The measures of chapter 2 of *Algorithmic Trading with Python* (Chris
Conlan, 2020), written here from their textbook definitions (the book's
own code is freeware for personal use only and is not copied). Every
function takes an equity curve (or prices) indexed by time, oldest first.

- growth: total return, CAGR (compound annual growth);
- risk: annualised volatility, downside deviation, maximum drawdown
  (on log prices, so a fall and the rise that undoes it weigh the same);
- reward per risk: Sharpe, Sortino, Calmar (CAGR over the worst fall of
  the last years), and the log max-drawdown ratio;
- shape: the "pure profit score", the R² of a straight line through the
  log equity times its CAGR, which rewards growth that is steady;
- against a benchmark: Jensen's alpha, the return a strategy earned beyond
  what its exposure to the benchmark (its beta) explains.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

YEAR = 365.25 * 86400


def _years(series: pd.Series) -> float:
    idx = series.index
    if len(idx) < 2:
        return 0.0
    if isinstance(idx, pd.DatetimeIndex):
        return (idx[-1] - idx[0]).total_seconds() / YEAR
    return float(idx[-1] - idx[0]) / YEAR                 # unix seconds


def periods_per_year(series: pd.Series) -> float:
    """Observations per year, from the series' own timestamps."""
    years = _years(series)
    return (len(series) - 1) / years if years > 0 else float("nan")


def returns(series: pd.Series) -> pd.Series:
    return series.pct_change().dropna()


def log_returns(series: pd.Series) -> pd.Series:
    return np.log(series).diff().dropna()


def total_return(series: pd.Series) -> float:
    return float(series.iloc[-1] / series.iloc[0] - 1)


def cagr(series: pd.Series) -> float:
    years = _years(series)
    if years <= 0 or series.iloc[0] <= 0 or series.iloc[-1] <= 0:
        return float("nan")
    return float((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1)


def volatility(series: pd.Series) -> float:
    """Annualised standard deviation of the period returns."""
    r = returns(series)
    return float(r.std() * math.sqrt(periods_per_year(series))) if len(r) > 1 else float("nan")


def downside_deviation(series: pd.Series, target: float = 0.0) -> float:
    """Annualised deviation of the returns below `target` (per period)."""
    r = returns(series)
    if len(r) < 2:
        return float("nan")
    below = np.minimum(r - target, 0.0)
    return float(math.sqrt((below ** 2).mean()) * math.sqrt(periods_per_year(series)))


def sharpe(series: pd.Series, risk_free: float = 0.0) -> float:
    vol = volatility(series)
    return (cagr(series) - risk_free) / vol if vol and vol == vol else float("nan")


def sortino(series: pd.Series, risk_free: float = 0.0) -> float:
    dd = downside_deviation(series)
    return (cagr(series) - risk_free) / dd if dd and dd == dd else float("nan")


def drawdown_series(series: pd.Series, log: bool = True) -> pd.Series:
    """How far below its running high the curve is at each point (≥ 0)."""
    if log:
        lp = np.log(series)
        return lp.cummax() - lp
    return 1 - series / series.cummax()


def max_drawdown(series: pd.Series, log: bool = True) -> float:
    return float(drawdown_series(series, log).max())


def max_drawdown_info(series: pd.Series) -> dict:
    """The worst fall (as a fraction), when it peaked, bottomed and recovered."""
    dd = drawdown_series(series, log=False)
    bottom = dd.idxmax()
    peak = series.loc[:bottom].idxmax()
    after = series.loc[bottom:]
    recovered = after[after >= series.loc[peak]]
    return {"drawdown": float(dd.max()), "peak": peak, "bottom": bottom,
            "recovered": recovered.index[0] if len(recovered) else None}


def log_drawdown_ratio(series: pd.Series) -> float:
    """Log growth over the worst log fall: how many worst falls it earned."""
    mdd = max_drawdown(series, log=True)
    growth = float(np.log(series.iloc[-1] / series.iloc[0]))
    return growth / mdd if mdd > 0 else float("inf")


def calmar(series: pd.Series, years: float = 3.0) -> float:
    """CAGR over the worst fall, both over the last `years`."""
    end = series.index[-1]
    cut = (end - pd.Timedelta(days=365.25 * years) if isinstance(series.index, pd.DatetimeIndex)
           else end - years * YEAR)
    recent = series[series.index >= cut]
    mdd = max_drawdown(recent, log=False)
    return cagr(recent) / mdd if mdd > 0 else float("inf")


def pure_profit_score(series: pd.Series) -> float:
    """CAGR times the R² of a straight line through the log equity: steady
    growth scores close to its CAGR, a lucky jump much less."""
    y = np.log(series.to_numpy(float))
    if len(y) < 3:
        return float("nan")
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    return cagr(series) * r2


def jensens_alpha(series: pd.Series, benchmark: pd.Series) -> float:
    """Annualised return beyond what beta times the benchmark explains."""
    both = pd.concat([returns(series), returns(benchmark)], axis=1, join="inner").dropna()
    if len(both) < 3:
        return float("nan")
    r, b = both.iloc[:, 0], both.iloc[:, 1]
    var = float(b.var())
    beta = float(r.cov(b) / var) if var > 0 else 0.0
    alpha = float(r.mean() - beta * b.mean())
    return alpha * periods_per_year(series)


def beta(series: pd.Series, benchmark: pd.Series) -> float:
    both = pd.concat([returns(series), returns(benchmark)], axis=1, join="inner").dropna()
    var = float(both.iloc[:, 1].var()) if len(both) > 2 else 0.0
    return float(both.iloc[:, 0].cov(both.iloc[:, 1]) / var) if var > 0 else float("nan")


def report_card(series: pd.Series, benchmark: pd.Series | None = None) -> dict:
    """Every measure of the course for one curve."""
    card = {"total": total_return(series), "cagr": cagr(series), "volatility": volatility(series),
            "sharpe": sharpe(series), "sortino": sortino(series),
            "max_drawdown": max_drawdown(series, log=False), "calmar": calmar(series),
            "pure_profit": pure_profit_score(series)}
    if benchmark is not None:
        card["beta"] = beta(series, benchmark)
        card["alpha"] = jensens_alpha(series, benchmark)
    return card
