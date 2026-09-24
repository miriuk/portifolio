"""The building's floors: one colony per asset class, same rules, different
tape, clock and specialists.

- crypto: hourly candles from Kraken, 24 bars a day, seven days a week.
- stocks: daily bars of US stocks and ETFs (Nasdaq's API on GitHub, Stooq
  from a home connection), one bar a trading day, five days a week.

A floor bundles the founders (with parameters on the right time scale),
the survival configuration, the live feed, and where its state lives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .agents.rules import (BreakoutAgent, BuyAndHoldAgent, MeanReversionAgent, MomentumAgent,
                           RegimeSwitchAgent, TrendFollowerAgent, VolTargetAgent)
from .arena.survival import SurvivalConfig

REPO = "miriuk/portifolio"


@dataclass
class Floor:
    name: str
    label: str
    caption: str
    build_founders: Callable[[float], list]
    config_defaults: dict = field(default_factory=dict)
    make_feed: Callable[..., object] = None
    default_db: str = "live/colony.db"
    state_branch: str = "colony-live"
    data_dir: str = "data"
    warmup: int = 700
    backtest_days: int = 30
    backtest_stride: int = 10

    @property
    def live_url(self) -> str:
        return f"https://raw.githubusercontent.com/{REPO}/{self.state_branch}/colony.db"

    def config(self, **overrides) -> SurvivalConfig:
        return SurvivalConfig(**{**self.config_defaults, **overrides})


def crypto_founders(cash: float) -> list:
    return [
        MomentumAgent("momentum-1", cash),
        MomentumAgent("momentum-2", cash, params={"lookback": 336, "entry_threshold": 0.08,
                                                  "exit_threshold": -0.04}),
        MeanReversionAgent("meanrev-1", cash),
        MeanReversionAgent("meanrev-2", cash, params={"lookback": 240, "entry_threshold": 0.10}),
        BreakoutAgent("breakout-1", cash),
        RegimeSwitchAgent("regime-1", cash),
        VolTargetAgent("voltarget-1", cash),
        TrendFollowerAgent("trend-1", cash),
        # not a founder: BearAgent, the paper short seller. On 13 months of
        # falling tape it was the only founder in the black; on five years
        # (2021-2026, 184 windows) every variant lost, even in 2022 — fees
        # plus 0.12%/day of funding eat what shorting makes. Available to hire.
    ]


# Daily bars: a 168-hour lookback becomes 20 trading days and cooldowns
# are days, not hours. Six years of real bars (2020-2026, a strong bull
# run for these names) said the crypto floor's gates only cost
# participation here: a short 3-month trend filter, full exposure allowed,
# no market gate, no rank filter, bigger orders.
STOCK_SHARED = {"trend_filter": 60, "cooldown": 3, "market_gate": 0, "rank_top": 0,
                "max_exposure": 1.0, "order_frac": 0.5}


def stock_founders(cash: float) -> list:
    p = STOCK_SHARED
    return [
        MomentumAgent("momentum-1", cash, params={**p, "lookback": 20, "entry_threshold": 0.03,
                                                  "exit_threshold": -0.02}),
        MomentumAgent("momentum-2", cash, params={**p, "lookback": 60, "entry_threshold": 0.06,
                                                  "exit_threshold": -0.03}),
        MeanReversionAgent("meanrev-1", cash, params={**p, "lookback": 20, "entry_threshold": 0.05,
                                                      "exit_gain": 0.03, "stop_trail": 0.06}),
        MeanReversionAgent("meanrev-2", cash, params={**p, "lookback": 50, "entry_threshold": 0.08,
                                                      "exit_gain": 0.04, "stop_trail": 0.06}),
        BreakoutAgent("breakout-1", cash, params={**p, "lookback": 20, "trail_pct": 0.08}),
        RegimeSwitchAgent("regime-1", cash, params={**p, "lookback": 60, "trend_threshold": 0.06,
                                                    "entry_threshold": 0.03}),
        VolTargetAgent("voltarget-1", cash, params={**p, "lookback": 60, "entry_threshold": 0.04,
                                                    "vol_exit": 0.03}),
        TrendFollowerAgent("trend-1", cash, params={**p, "fast": 10, "slow": 50,
                                                    "exit_buffer": 0.02}),
        BuyAndHoldAgent("index-1", cash, hold_symbols=["SPY", "QQQ"]),
    ]


def _crypto_feed(exchange_id: str = "kraken", symbols: dict | None = None,
                 timeframe: str = "1h"):
    from .market.live import LiveFeed, majors_symbols
    return LiveFeed(exchange_id, symbols or majors_symbols(exchange_id), timeframe=timeframe)


def _stock_feed(exchange_id: str = "stooq", symbols: dict | None = None, timeframe: str = "1d"):
    from .market.stocks import StooqFeed
    return StooqFeed(symbols)


FLOORS: dict[str, Floor] = {
    "crypto": Floor(
        name="crypto", label="Crypto",
        caption="24 majors at real Kraken prices, paper wallets, a real day per day",
        build_founders=crypto_founders,
        config_defaults=dict(endogenous=False),
        make_feed=_crypto_feed,
        default_db="live/colony.db", state_branch="colony-live", data_dir="data",
        warmup=700, backtest_days=30, backtest_stride=10,
    ),
    "stocks": Floor(
        name="stocks", label="Stocks",
        caption="daily bars of SPY, QQQ, Apple, Microsoft, Nvidia and Amazon from Nasdaq, "
                "paper wallets, one day per trading day",
        build_founders=stock_founders,
        config_defaults=dict(endogenous=False, steps_per_day=1, week_days=5,
                             daily_target=0.002, fee_rate=0.0005),
        make_feed=_stock_feed,
        default_db="live/stocks.db", state_branch="colony-live-stocks", data_dir="data/stocks",
        warmup=250, backtest_days=60, backtest_stride=20,
    ),
}


def get_floor(name: str) -> Floor:
    try:
        return FLOORS[name]
    except KeyError:
        raise SystemExit(f"unknown floor {name!r}; choose from {', '.join(FLOORS)}") from None
