from __future__ import annotations

from ..market.exchange import Order
from .base import MarketView, TradingAgent


class ParamAgent(TradingAgent):
    """Rule agent with numeric parameters that evolution can mutate and
    that reflection lessons can nudge directly."""

    DEFAULTS: dict[str, float] = {}

    def __init__(self, agent_id: str, starting_cash: float = 10_000.0,
                 params: dict | None = None):
        super().__init__(agent_id, starting_cash)
        self.params = {**self.DEFAULTS, **(params or {})}

    def get_params(self) -> dict:
        return dict(self.params)

    def set_params(self, params: dict) -> None:
        self.params.update({k: v for k, v in params.items() if k in self.DEFAULTS})

    def clone(self, agent_id: str, starting_cash: float, rng=None,
              mutate: bool = False) -> "ParamAgent":
        from collections import deque
        params = dict(self.params)
        if mutate:
            import numpy as np
            from ..learning.evolution import mutate_params
            params = mutate_params(params, rng or np.random.default_rng())
        child = type(self)(agent_id, starting_cash, params=params)
        # born with the parent's view of the market, so indicators work on day one
        child.history = {sym: deque(h, maxlen=h.maxlen) for sym, h in self.history.items()}
        return child

    def imitate(self, params: dict, rate: float) -> None:
        for key, target in params.items():
            if key not in self.DEFAULTS or isinstance(target, bool) \
                    or not isinstance(target, (int, float)):
                continue
            mine = self.params.get(key, self.DEFAULTS[key])
            moved = mine + rate * (target - mine)
            self.params[key] = type(self.DEFAULTS[key])(round(moved) if isinstance(
                self.DEFAULTS[key], int) else moved)

    def _can_buy(self) -> bool:
        """Enough cash to place an order worth having — relative to the
        agent's own budget, so a small intern can trade too."""
        return self.wallet.cash > max(self.starting_cash * 0.05, 1.0)

    def learn(self, lessons: list[str]) -> None:
        """Map lesson themes onto parameter nudges — errors change behavior.

        Every nudge is clamped to a band around the strategy defaults so
        repeated lessons cannot drive the agent into total paralysis (or
        recklessness); the 'too passive' lesson pushes the other way.
        """
        base_entry = self.DEFAULTS.get("entry_threshold", 0.01)
        base_cd = self.DEFAULTS.get("cooldown", 4)
        for lesson in lessons:
            if "stop-losses" in lesson or "too aggressive" in lesson:
                self.params["entry_threshold"] = min(
                    self.params.get("entry_threshold", base_entry) * 1.1, base_entry * 2)
            if "overtrading" in lesson:
                self.params["cooldown"] = min(
                    self.params.get("cooldown", base_cd) * 1.25, base_cd * 3)
            if "missed the move" in lesson:
                self.params["entry_threshold"] = max(
                    self.params.get("entry_threshold", base_entry) * 0.9, base_entry * 0.6)
                self.params["cooldown"] = max(
                    self.params.get("cooldown", base_cd) * 0.8, base_cd * 0.5)
            if "sizing too large" in lesson:
                self.params["order_frac"] = max(self.params.get("order_frac", 0.15) * 0.7, 0.02)
            if "lean into this setup" in lesson:
                self.params["order_frac"] = min(self.params.get("order_frac", 0.15) * 1.15, 0.30)

    def _order_amount(self, view: MarketView) -> float:
        return self.wallet.equity(view.prices) * self.params.get("order_frac", 0.15)

    # --- shared discipline: every rule agent gets a trailing stop and a trend filter
    def decide(self, view: MarketView) -> list[Order]:
        """Protective exits first, then the strategy's own orders, minus
        any buy the trend filter or a just-triggered stop vetoes. With a
        wide universe two more disciplines apply: at most `max_buys` new
        positions per bar (the strongest trend wins) and no new buys once
        `max_exposure` of equity is already invested. `greed_gate` (0 = off)
        vetoes new buys while the Crypto Fear & Greed index is above it."""
        orders = self._protective_exits(view)
        stopped = {o.symbol for o in orders}
        buys: list[Order] = []
        for order in self._decide(view):
            if order.side == "buy" and not order.base_qty:
                if order.symbol in stopped or not self._trend_ok(order.symbol):
                    continue
                buys.append(order)
            else:                                # sells, and covers of a short, pass as they are
                orders.append(order)
        if buys and not self._market_ok():
            buys = []
        greed = float(self.params.get("greed_gate", 0) or 0)
        if buys and greed and view.sentiment is not None and view.sentiment > greed:
            buys = []                            # no new longs while the crowd is greedy
        top = int(self.params.get("rank_top", 0) or 0)
        if top and buys:
            bars = int(self.params.get("trend_filter", 0) or 168)
            ranked = sorted(((self.momentum(sym, bars) or -9.0), sym) for sym in view.candles)
            leaders = {sym for _, sym in ranked[-top:]}
            buys = [o for o in buys if o.symbol in leaders]
        max_buys = int(self.params.get("max_buys", 0) or 0)
        if max_buys and len(buys) > max_buys:
            lookback = int(self.params.get("lookback", 168) or 168)
            buys.sort(key=lambda o: -(self.momentum(o.symbol, lookback) or 0.0))
            buys = buys[:max_buys]
        cap = float(self.params.get("max_exposure", 0.0) or 0.0)
        if cap and buys and self.wallet.exposure(view.prices) >= cap:
            buys = []
        return orders + buys

    def _decide(self, view: MarketView) -> list[Order]:   # strategies override this
        return []

    def _protective_exits(self, view: MarketView) -> list[Order]:
        """Trailing stop: `stop_trail` below the highest close seen while
        holding (0 = off). The high-water mark lives on the agent so a
        live colony can save and restore it."""
        trail = float(self.params.get("stop_trail", 0.0) or 0.0)
        hw: dict[str, float] = self.__dict__.setdefault("_stop_high", {})
        orders = []
        for symbol, candle in view.candles.items():
            held = self.wallet.positions.get(symbol, 0.0)
            if held == 0:
                hw.pop(symbol, None)
                continue
            if held < 0:                                   # a short: the mark is the low
                hw[symbol] = min(hw.get(symbol, candle.close), candle.close)
                if trail and candle.close > hw[symbol] * (1 + trail):
                    orders.append(Order(self.agent_id, symbol, "buy", 0.0, base_qty=-held,
                                        reason=f"trailing stop {trail:.0%} off the low"))
                    hw.pop(symbol, None)
                continue
            hw[symbol] = max(hw.get(symbol, candle.close), candle.close)
            if trail and candle.close < hw[symbol] * (1 - trail):
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason=f"trailing stop {trail:.0%} off the high"))
                hw.pop(symbol, None)
        return orders

    def _weather(self, bars: int) -> float | None:
        """The market's bellwether (the BTC pair, or the first symbol) over
        `bars`: the whole floor's weather, not one coin's."""
        if not bars or not self.history:
            return None
        bell = next((s for prefix in ("BTC", "SPY") for s in sorted(self.history)
                     if s.upper().startswith(prefix)), next(iter(sorted(self.history))))
        return self.momentum(bell, bars)

    def _market_ok(self) -> bool:
        """`market_gate` bars (0 = off): no new buys while the bellwether is
        below where it was that many bars ago."""
        mom = self._weather(int(self.params.get("market_gate", 0) or 0))
        return mom is None or mom > 0

    def _trend_ok(self, symbol: str) -> bool:
        """`trend_filter` bars (0 = off): only buy an asset trading above
        where it was that many bars ago — no knife-catching in a downtrend.
        Backtests on a year of real hourly data: the 28-day gate cut the
        colony's average 30-day loss by a third and its fees in half."""
        bars = int(self.params.get("trend_filter", 0) or 0)
        if not bars:
            return True
        mom = self.momentum(symbol, bars)
        return mom is not None and mom > 0


class MomentumAgent(ParamAgent):
    """Buys strength, sells weakness."""

    DEFAULTS = {"lookback": 168, "entry_threshold": 0.05, "exit_threshold": -0.03,
                "order_frac": 0.30, "cooldown": 24,
                "stop_trail": 0.0, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        for symbol in view.candles:
            mom = self.momentum(symbol, int(self.params["lookback"]))
            if mom is None:
                continue
            held = self.wallet.positions.get(symbol, 0.0)
            if mom > self.params["entry_threshold"] and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy",
                                    self._order_amount(view),
                                    reason=f"momentum {mom:+.2%}"))
                self._last_trade_step = view.step
            elif mom < self.params["exit_threshold"] and held > 0:
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason=f"momentum faded {mom:+.2%}"))
                self._last_trade_step = view.step
        return orders


class MeanReversionAgent(ParamAgent):
    """Buys dips below the moving average, sells back at/above it."""

    DEFAULTS = {"lookback": 168, "entry_threshold": 0.08, "exit_gain": 0.04,
                "order_frac": 0.15, "cooldown": 24,
                "stop_trail": 0.06, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        for symbol, candle in view.candles.items():
            avg = self.sma(symbol, int(self.params["lookback"]))
            if avg is None or avg <= 0:
                continue
            deviation = (candle.close - avg) / avg
            held = self.wallet.positions.get(symbol, 0.0)
            basis = self.wallet.cost_basis.get(symbol, 0.0)
            if deviation < -self.params["entry_threshold"] and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy",
                                    self._order_amount(view),
                                    reason=f"dip {deviation:+.2%} vs sma"))
                self._last_trade_step = view.step
            elif held > 0 and basis > 0 and candle.close > basis * (1 + self.params["exit_gain"]):
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="mean reversion target hit"))
                self._last_trade_step = view.step
        return orders


class RegimeSwitchAgent(ParamAgent):
    """Reads the regime from public data and changes playbook: rides
    trends when the market is trending, sits on its hands when it is
    ranging (fees win in chop), and goes flat when volatility says panic."""

    DEFAULTS = {"lookback": 168, "trend_threshold": 0.06, "entry_threshold": 0.03,
                "vol_panic": 0.03, "order_frac": 0.15, "cooldown": 24,
                "stop_trail": 0.0, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def regime(self, symbol: str) -> str:
        trend = self.momentum(symbol, int(self.params["lookback"]))
        vol = self.volatility(symbol, 24)
        if trend is None or vol is None:
            return "unknown"
        if vol > self.params["vol_panic"]:
            return "panic"
        if abs(trend) > self.params["trend_threshold"]:
            return "trending"
        return "ranging"

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        cooled = view.step - self._last_trade_step >= int(self.params["cooldown"])
        for symbol, candle in view.candles.items():
            held = self.wallet.positions.get(symbol, 0.0)
            regime = self.regime(symbol)
            if regime == "panic":
                if held > 0:
                    orders.append(Order(self.agent_id, symbol, "sell", held,
                                        reason="regime: panic, going flat"))
                continue
            if regime == "unknown" or not cooled:
                continue
            short = self.momentum(symbol, 12) or 0.0
            avg = self.sma(symbol, 48)
            if regime == "trending":
                trend = self.momentum(symbol, int(self.params["lookback"])) or 0.0
                if trend > 0 and short > self.params["entry_threshold"] / 2 and held == 0 \
                        and self._can_buy():
                    orders.append(Order(self.agent_id, symbol, "buy", self._order_amount(view),
                                        reason=f"regime: trending {trend:+.1%}, riding it"))
                    self._last_trade_step = view.step
                elif held > 0 and short < -self.params["entry_threshold"]:
                    orders.append(Order(self.agent_id, symbol, "sell", held,
                                        reason="regime: trend losing steam"))
                    self._last_trade_step = view.step
            elif held > 0 and avg and candle.close > avg:
                # ranging: no new bets; let a leftover position go at the mean
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="regime: ranging, sitting out"))
                self._last_trade_step = view.step
        return orders


class VolTargetAgent(ParamAgent):
    """Trend follower that sizes every position so the expected daily move
    of the position is a fixed slice of equity: bigger in calm markets,
    smaller in wild ones, and out when volatility explodes."""

    DEFAULTS = {"lookback": 168, "entry_threshold": 0.04, "target_vol": 0.01,
                "vol_exit": 0.04, "order_frac": 0.30, "cooldown": 24,
                "stop_trail": 0.0, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _sized_amount(self, view: MarketView, vol: float) -> float:
        equity = self.wallet.equity(view.prices)
        # risk budget / realized vol, capped at order_frac of equity
        frac = min(self.params["order_frac"], self.params["target_vol"] / max(vol, 1e-4) * 0.15)
        return equity * frac

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        for symbol in view.candles:
            mom = self.momentum(symbol, int(self.params["lookback"]))
            vol = self.volatility(symbol, 24)
            if mom is None or vol is None:
                continue
            held = self.wallet.positions.get(symbol, 0.0)
            if held > 0 and (vol > self.params["vol_exit"] or mom < -self.params["entry_threshold"] / 2):
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="vol spike" if vol > self.params["vol_exit"]
                                    else f"trend flipped {mom:+.1%}"))
                self._last_trade_step = view.step
            elif held == 0 and mom > self.params["entry_threshold"] \
                    and vol < self.params["vol_exit"] and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy", self._sized_amount(view, vol),
                                    reason=f"trend {mom:+.1%} at vol {vol:.1%}, vol-sized"))
                self._last_trade_step = view.step
        return orders


class BreakoutAgent(ParamAgent):
    """Buys new N-bar highs, exits on trailing weakness."""

    DEFAULTS = {"lookback": 168, "entry_threshold": 0.005, "trail_pct": 0.08,
                "order_frac": 0.30, "cooldown": 24,
                "stop_trail": 0.0, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999
        self._high_water: dict[str, float] = {}

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        for symbol, candle in view.candles.items():
            closes = self.closes(symbol, int(self.params["lookback"]))
            if len(closes) < int(self.params["lookback"]):
                continue
            prior_high = max(closes[:-1])
            held = self.wallet.positions.get(symbol, 0.0)
            if held > 0:
                hw = self._high_water.get(symbol, candle.close)
                self._high_water[symbol] = max(hw, candle.close)
                if candle.close < self._high_water[symbol] * (1 - self.params["trail_pct"]):
                    orders.append(Order(self.agent_id, symbol, "sell", held,
                                        reason="trailing stop"))
                    self._high_water.pop(symbol, None)
                continue
            cooled = view.step - self._last_trade_step >= int(self.params["cooldown"])
            if cooled and candle.close > prior_high * (1 + self.params["entry_threshold"]) \
                    and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy",
                                    self._order_amount(view),
                                    reason=f"breakout above {prior_high:.2f}"))
                self._last_trade_step = view.step
                self._high_water[symbol] = candle.close
        return orders


class TrendFollowerAgent(ParamAgent):
    """The classic daily-horizon trend rule: long while the fast moving
    average sits above the slow one and price is above both, flat
    otherwise. Few trades (a handful a month per coin), so fees stay
    small; it gives up the first leg of every move to skip the crashes."""

    DEFAULTS = {"fast": 72, "slow": 240, "order_frac": 0.30, "cooldown": 12,
                "exit_buffer": 0.02, "stop_trail": 0.0, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        for symbol, candle in view.candles.items():
            fast = self.sma(symbol, int(self.params["fast"]))
            slow = self.sma(symbol, int(self.params["slow"]))
            if fast is None or slow is None:
                continue
            held = self.wallet.positions.get(symbol, 0.0)
            up = fast > slow and candle.close > fast
            down = fast < slow * (1 - self.params["exit_buffer"]) or \
                candle.close < slow * (1 - self.params["exit_buffer"])
            if held == 0 and up and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy", self._order_amount(view),
                                    reason=f"trend: fast {fast / slow - 1:+.1%} above slow"))
                self._last_trade_step = view.step
            elif held > 0 and down:
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="trend: crossed down, flat"))
                self._last_trade_step = view.step
        return orders


class RotationAgent(ParamAgent):
    """Cross-sectional momentum: every `rebalance` bars, hold the `top`
    coins with the strongest `lookback` momentum (only ones going up),
    equal-weighted, and drop whatever fell out of the leaders. Between
    rebalances only the trailing stop acts. The classic crypto rotation."""

    DEFAULTS = {"lookback": 336, "top": 3, "rebalance": 168, "entry_threshold": 0.0,
                "order_frac": 0.30, "cooldown": 168,
                "stop_trail": 0.10, "trend_filter": 672,
                "max_buys": 3, "max_exposure": 0.9, "market_gate": 672, "rank_top": 0, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        if view.step - self._last_trade_step < int(self.params["rebalance"]):
            return []
        lookback = int(self.params["lookback"])
        ranked = sorted(((mom, sym) for sym in view.candles
                         if (mom := self.momentum(sym, lookback)) is not None
                         and mom > self.params["entry_threshold"]), reverse=True)
        leaders = [sym for _, sym in ranked[:int(self.params["top"])]]
        orders = []
        for sym, held in list(self.wallet.positions.items()):
            if held > 0 and sym not in leaders and sym in view.candles:
                orders.append(Order(self.agent_id, sym, "sell", held,
                                    reason="rotation: out of the leaders"))
        for rank, sym in enumerate(leaders, 1):
            if self.wallet.positions.get(sym, 0.0) <= 0 and self._can_buy():
                orders.append(Order(self.agent_id, sym, "buy", self._order_amount(view),
                                    reason=f"rotation: #{rank} momentum"))
        if orders:
            self._last_trade_step = view.step
        return orders


class PullbackAgent(ParamAgent):
    """Buys a dip inside an uptrend: the coin is above where it was
    `trend_filter` bars ago (the gate), yet `entry_threshold` below its
    `lookback`-bar high. Sells `exit_gain` above the entry, or on the trail."""

    DEFAULTS = {"lookback": 168, "entry_threshold": 0.08, "exit_gain": 0.06,
                "order_frac": 0.30, "cooldown": 24,
                "stop_trail": 0.08, "trend_filter": 672,
                "max_buys": 1, "max_exposure": 0.6, "market_gate": 672, "rank_top": 6, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        cooled = view.step - self._last_trade_step >= int(self.params["cooldown"])
        lookback = int(self.params["lookback"])
        for symbol, candle in view.candles.items():
            closes = self.closes(symbol, lookback)
            if len(closes) < lookback:
                continue
            high = max(closes)
            dip = (candle.close - high) / high
            held = self.wallet.positions.get(symbol, 0.0)
            basis = self.wallet.cost_basis.get(symbol, 0.0)
            if held <= 0 and cooled and dip < -self.params["entry_threshold"] and self._can_buy():
                orders.append(Order(self.agent_id, symbol, "buy", self._order_amount(view),
                                    reason=f"pullback {dip:+.1%} off the {lookback // 24}d high"))
                self._last_trade_step = view.step
            elif held > 0 and basis > 0 and candle.close > basis * (1 + self.params["exit_gain"]):
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="pullback target hit"))
                self._last_trade_step = view.step
        return orders


class BearAgent(ParamAgent):
    """The short seller. When the bellwether is below where it was
    `market_gate` bars ago (by at least `weather_min`, e.g. -0.10 for a
    real downtrend rather than a dip; `fear_max` > 0 also asks the Fear &
    Greed index to be at or under it), shorts the weakest coins: `lookback` momentum
    under -`entry_threshold` and still below their `trend_filter` level.
    Covers when the drop is bought (`lookback` momentum back above
    -`exit_threshold`; the default waits for a clear +5% bounce, which a
    year of real bars preferred to covering at the first green candle),
    at `take_profit` under the entry, or on the trailing stop above the
    low. Paper margin: the position goes negative,
    the proceeds sit in cash, and the short pays its funding every day."""

    allow_short = True
    DEFAULTS = {"lookback": 168, "entry_threshold": 0.05, "exit_threshold": -0.05,
                "take_profit": 0.12, "max_shorts": 2, "weather_min": 0.0, "fear_max": 0,
                "order_frac": 0.30, "cooldown": 24,
                "stop_trail": 0.08, "trend_filter": 672,
                "max_buys": 0, "max_exposure": 0.0, "market_gate": 672, "rank_top": 0, "greed_gate": 60}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def _decide(self, view: MarketView) -> list[Order]:
        orders = []
        lookback = int(self.params["lookback"])
        for symbol, held in list(self.wallet.positions.items()):
            if held >= 0 or symbol not in view.candles:
                continue
            mom = self.momentum(symbol, lookback)
            basis = self.wallet.cost_basis.get(symbol, 0.0)
            price = view.prices[symbol]
            if mom is not None and mom > -self.params["exit_threshold"]:
                orders.append(Order(self.agent_id, symbol, "buy", 0.0, base_qty=-held,
                                    reason=f"cover: the drop is bought {mom:+.1%}"))
            elif basis > 0 and price < basis * (1 - self.params["take_profit"]):
                orders.append(Order(self.agent_id, symbol, "buy", 0.0, base_qty=-held,
                                    reason=f"cover: take profit {price / basis - 1:+.1%}"))
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        weather = self._weather(int(self.params.get("market_gate", 0) or 0))
        if weather is None or weather >= min(0.0, float(self.params.get("weather_min", 0.0))):
            return orders                                   # no shorting into a rising market
        fear_max = float(self.params.get("fear_max", 0) or 0)
        if fear_max and view.sentiment is not None and view.sentiment > fear_max:
            return orders                                   # only short once the crowd is already afraid
        open_shorts = sum(1 for q in self.wallet.positions.values() if q < 0)
        room = int(self.params["max_shorts"]) - open_shorts
        if room <= 0:
            return orders
        trend_bars = int(self.params.get("trend_filter", 0) or 0)
        weakest = sorted(
            (mom, sym) for sym in view.candles
            if self.wallet.positions.get(sym, 0.0) == 0
            and (mom := self.momentum(sym, lookback)) is not None
            and mom < -self.params["entry_threshold"]
            and (not trend_bars or (self.momentum(sym, trend_bars) or 0.0) < 0))
        for mom, sym in weakest[:room]:
            price = view.prices[sym]
            if price <= 0:
                continue
            orders.append(Order(self.agent_id, sym, "sell", self._order_amount(view) / price,
                                reason=f"short {mom:+.1%}"))
            self._last_trade_step = view.step
        return orders


class BuyAndHoldAgent(ParamAgent):
    """The passive investor: buys `hold_symbols` (or everything) in equal
    weights on the first bar it can, then sits. No exits, no signals — the
    yardstick every active specialist on the floor is measured against,
    and in a long bull market the one the interns end up imitating."""

    DEFAULTS = {"order_frac": 0.45, "cooldown": 1, "stop_trail": 0.0, "trend_filter": 0,
                "max_buys": 0, "max_exposure": 0.0, "market_gate": 0, "rank_top": 0}

    def __init__(self, *args, hold_symbols: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hold_symbols = list(hold_symbols or [])

    def _decide(self, view: MarketView) -> list[Order]:
        wanted = [s for s in view.candles if not self.hold_symbols or s in self.hold_symbols]
        if not wanted:
            return []
        orders = []
        for symbol in wanted:
            if self.wallet.positions.get(symbol, 0.0) > 0 or not self._can_buy():
                continue
            orders.append(Order(self.agent_id, symbol, "buy",
                                self.wallet.equity(view.prices) * self.params["order_frac"],
                                reason="buy and hold"))
        return orders

    def learn(self, lessons: list[str]) -> None:
        """Holding is the whole idea; no lesson changes it."""

    def clone(self, agent_id: str, starting_cash: float, rng=None, mutate: bool = False):
        child = super().clone(agent_id, starting_cash, rng, mutate=False)
        child.hold_symbols = list(self.hold_symbols)
        return child
