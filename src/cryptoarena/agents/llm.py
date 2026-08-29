from __future__ import annotations

import os

from pydantic import BaseModel, Field

from ..market.exchange import Order
from .base import MarketView, TradingAgent

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are {agent_id}, an autonomous crypto trading agent competing \
in a simulated market arena against other agents. You manage a paper wallet and are \
judged on risk-adjusted returns across episodes.

Your persona: {persona}

Rules of the arena:
- Market orders only; every trade pays fees and slippage, and oversized orders \
slip more. Overtrading loses money.
- A risk manager clips your orders (max position 35% of equity, max order 25%) and \
force-sells any position down 12% from your entry. Repeated stop-outs mean your \
entries are bad.
- The market switches between hidden regimes (trend, chop, mania, crash). \
What worked last week may fail this week.

You have a persistent journal. Lessons from your own past episodes:
{lessons}

Decide based on the data given, respecting your lessons. It is often correct to do \
nothing. Only trade when you see a real edge."""


class TradeDecision(BaseModel):
    symbol: str = Field(description="symbol to trade")
    action: str = Field(description="'buy' or 'sell'")
    fraction: float = Field(ge=0.0, le=0.3, description=(
        "buy: fraction of equity to spend; sell: fraction of the held position to sell"
    ))
    rationale: str = Field(description="one short sentence explaining the trade")


class DecisionSet(BaseModel):
    market_read: str = Field(description="one-sentence read of current conditions")
    decisions: list[TradeDecision] = Field(description="orders to place; empty list to hold")


class ClaudeTraderAgent(TradingAgent):
    """LLM-driven trader: decides via structured output, learns via lessons
    injected into its system prompt, and writes its own reflection after
    each episode (the TradingAgents/FinMem pattern).

    Requires ANTHROPIC_API_KEY (or an `ant auth login` profile). To keep
    token costs sane it decides every `decision_interval` bars, not every bar.
    """

    def __init__(self, agent_id: str, starting_cash: float = 10_000.0,
                 persona: str = "disciplined swing trader; patient, hates leverage and hype",
                 model: str = DEFAULT_MODEL, decision_interval: int = 24,
                 client=None):
        super().__init__(agent_id, starting_cash)
        self.persona = persona
        self.model = model
        self.decision_interval = decision_interval
        self._lessons: list[str] = []
        self._client = client
        self.api_calls = 0

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def learn(self, lessons: list[str]) -> None:
        self._lessons.extend(lessons)
        self._lessons = self._lessons[-12:]

    def _market_summary(self, view: MarketView) -> str:
        lines = []
        for symbol, candle in sorted(view.candles.items()):
            mom24 = self.momentum(symbol, 24)
            mom72 = self.momentum(symbol, 72)
            vol = self.volatility(symbol, 24)
            held = self.wallet.positions.get(symbol, 0.0)
            basis = self.wallet.cost_basis.get(symbol, 0.0)
            pos = ""
            if held > 0:
                unreal = (candle.close - basis) / basis if basis > 0 else 0.0
                pos = f" | position: {held:.6f} @ {basis:.2f} ({unreal:+.1%})"
            lines.append(
                f"{symbol}: price {candle.close:.2f}, 24h {mom24:+.2%}" if mom24 is not None
                else f"{symbol}: price {candle.close:.2f}, 24h n/a"
            )
            if mom72 is not None and vol is not None:
                lines[-1] += f", 72h {mom72:+.2%}, vol24 {vol:.3%}"
            lines[-1] += pos
        equity = self.wallet.equity(view.prices)
        lines.append(f"cash: {self.wallet.cash:.2f} | equity: {equity:.2f} "
                     f"| exposure: {self.wallet.exposure(view.prices):.0%}")
        return "\n".join(lines)

    def decide(self, view: MarketView) -> list[Order]:
        if view.step % self.decision_interval != 0 or view.step < 72:
            return []
        lessons = "\n".join(f"- {l}" for l in self._lessons) or "- (no lessons yet)"
        system = SYSTEM_PROMPT.format(agent_id=self.agent_id, persona=self.persona,
                                      lessons=lessons)
        prompt = (f"Step {view.step}. Current market state:\n\n{self._market_summary(view)}\n\n"
                  "Return your decisions.")
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=DecisionSet,
            )
            self.api_calls += 1
            decisions = response.parsed_output
        except Exception as exc:  # network/auth/refusal: hold rather than crash the arena
            print(f"[{self.agent_id}] LLM call failed, holding: {exc}")
            return []

        orders = []
        equity = self.wallet.equity(view.prices)
        for d in decisions.decisions:
            if d.symbol not in view.prices or d.fraction <= 0:
                continue
            if d.action == "buy":
                orders.append(Order(self.agent_id, d.symbol, "buy",
                                    equity * d.fraction, reason=f"llm: {d.rationale}"))
            elif d.action == "sell":
                held = self.wallet.positions.get(d.symbol, 0.0)
                if held > 0:
                    orders.append(Order(self.agent_id, d.symbol, "sell",
                                        held * min(d.fraction / 0.3, 1.0),
                                        reason=f"llm: {d.rationale}"))
        return orders

    def reflect(self, episode: int, stats_text: str, trades_text: str) -> str | None:
        """Ask Claude for a one-paragraph lesson from the episode's outcomes."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=(f"You are {self.agent_id}, reviewing your own trading episode. "
                        "Write ONE short paragraph (max 60 words) stating the single most "
                        "important lesson for your future self: what to repeat, what to "
                        "stop doing. Be specific about conditions (regime, momentum, "
                        "sizing). No preamble."),
                messages=[{"role": "user", "content":
                           f"Episode {episode} results:\n{stats_text}\n\n"
                           f"Your closed trades:\n{trades_text}"}],
            )
            self.api_calls += 1
            text = next((b.text for b in response.content if b.type == "text"), "").strip()
            return f"episode {episode} (self-reflection): {text}" if text else None
        except Exception as exc:
            print(f"[{self.agent_id}] reflection failed: {exc}")
            return None
