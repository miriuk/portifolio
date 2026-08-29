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
                    self.params.get("entry_threshold", base_entry) * 1.2, base_entry * 3)
            if "overtrading" in lesson:
                self.params["cooldown"] = min(
                    self.params.get("cooldown", base_cd) * 1.5, 24)
            if "too passive" in lesson:
                self.params["entry_threshold"] = max(
                    self.params.get("entry_threshold", base_entry) * 0.8, base_entry * 0.3)
                self.params["cooldown"] = max(
                    self.params.get("cooldown", base_cd) * 0.7, 1)
            if "sizing too large" in lesson:
                self.params["order_frac"] = max(self.params.get("order_frac", 0.15) * 0.7, 0.02)
            if "lean into this setup" in lesson:
                self.params["order_frac"] = min(self.params.get("order_frac", 0.15) * 1.15, 0.30)

    def _order_amount(self, view: MarketView) -> float:
        return self.wallet.equity(view.prices) * self.params.get("order_frac", 0.15)


class MomentumAgent(ParamAgent):
    """Buys strength, sells weakness."""

    DEFAULTS = {"lookback": 24, "entry_threshold": 0.02, "exit_threshold": -0.01,
                "order_frac": 0.15, "cooldown": 4}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def decide(self, view: MarketView) -> list[Order]:
        orders = []
        if view.step - self._last_trade_step < int(self.params["cooldown"]):
            return orders
        for symbol in view.candles:
            mom = self.momentum(symbol, int(self.params["lookback"]))
            if mom is None:
                continue
            held = self.wallet.positions.get(symbol, 0.0)
            if mom > self.params["entry_threshold"] and self.wallet.cash > 100:
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

    DEFAULTS = {"lookback": 48, "entry_threshold": 0.04, "exit_gain": 0.03,
                "order_frac": 0.15, "cooldown": 6}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999

    def decide(self, view: MarketView) -> list[Order]:
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
            if deviation < -self.params["entry_threshold"] and self.wallet.cash > 100:
                orders.append(Order(self.agent_id, symbol, "buy",
                                    self._order_amount(view),
                                    reason=f"dip {deviation:+.2%} vs sma"))
                self._last_trade_step = view.step
            elif held > 0 and basis > 0 and candle.close > basis * (1 + self.params["exit_gain"]):
                orders.append(Order(self.agent_id, symbol, "sell", held,
                                    reason="mean reversion target hit"))
                self._last_trade_step = view.step
        return orders


class BreakoutAgent(ParamAgent):
    """Buys new N-bar highs, exits on trailing weakness."""

    DEFAULTS = {"lookback": 72, "entry_threshold": 0.005, "trail_pct": 0.06,
                "order_frac": 0.15, "cooldown": 8}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trade_step = -999
        self._high_water: dict[str, float] = {}

    def decide(self, view: MarketView) -> list[Order]:
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
                    and self.wallet.cash > 100:
                orders.append(Order(self.agent_id, symbol, "buy",
                                    self._order_amount(view),
                                    reason=f"breakout above {prior_high:.2f}"))
                self._last_trade_step = view.step
                self._high_water[symbol] = candle.close
        return orders
