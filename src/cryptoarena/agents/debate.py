"""Bull-vs-bear debate before trading decisions.

Ported from the TradingAgents pattern (TauricResearch/TradingAgents,
Apache-2.0; arXiv 2412.20138): a Bull analyst argues for buying, a Bear
analyst counters it, and a judge converts the debate into a structured
rating the trader must weigh. The debate forces the model to consider
both sides instead of anchoring on its first read of the market.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

BULL_PROMPT = """You are the Bull Analyst in a trading-desk debate about a \
simulated crypto portfolio. Build the strongest evidence-based case for \
adding exposure NOW, using only the data below. Attack the bear's argument \
directly if one is given. Be concrete: cite the numbers. Max 120 words.

Market state:
{market}

Lessons this desk has learned from past episodes:
{lessons}

Last bear argument (empty in round one):
{bear}"""

BEAR_PROMPT = """You are the Bear Analyst in a trading-desk debate about a \
simulated crypto portfolio. Build the strongest evidence-based case for \
caution or reducing exposure NOW, using only the data below. Attack the \
bull's argument directly. Be concrete: cite the numbers. Max 120 words.

Market state:
{market}

Lessons this desk has learned from past episodes:
{lessons}

Bull argument to rebut:
{bull}"""

JUDGE_PROMPT = """You are the Research Manager judging a bull-vs-bear debate. \
Weigh the arguments on evidence quality, not eloquence. Commit to a clear \
stance when one side's case is stronger; reserve 'hold' for genuinely \
balanced evidence.

Market state:
{market}

Debate transcript:
{transcript}"""


class DebateVerdict(BaseModel):
    rating: str = Field(description=(
        "exactly one of: 'buy' (strong bull case), 'overweight' (lean bullish), "
        "'hold' (balanced), 'underweight' (lean bearish), 'sell' (strong bear case)"
    ))
    conviction: float = Field(ge=0.0, le=1.0, description="confidence in the rating")
    plan: str = Field(description="two-sentence actionable plan for the trader")


@dataclass
class DebateResult:
    bull: str
    bear: str
    verdict: DebateVerdict

    @property
    def transcript(self) -> str:
        return f"Bull Analyst: {self.bull}\n\nBear Analyst: {self.bear}"


def _text_of(response) -> str:
    return next((b.text for b in response.content if b.type == "text"), "").strip()


def run_debate(client, model: str, market: str, lessons: str,
               rounds: int = 1, max_tokens: int = 1000) -> DebateResult:
    """One or more bull/bear rounds, then a structured judgment."""
    bull_arg, bear_arg = "", ""
    transcript_parts: list[str] = []
    for _ in range(max(rounds, 1)):
        bull_arg = _text_of(client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": BULL_PROMPT.format(
                market=market, lessons=lessons, bear=bear_arg or "(none yet)")}],
        ))
        transcript_parts.append(f"Bull Analyst: {bull_arg}")
        bear_arg = _text_of(client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": BEAR_PROMPT.format(
                market=market, lessons=lessons, bull=bull_arg)}],
        ))
        transcript_parts.append(f"Bear Analyst: {bear_arg}")

    verdict = client.messages.parse(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(
            market=market, transcript="\n\n".join(transcript_parts))}],
        output_format=DebateVerdict,
    ).parsed_output

    return DebateResult(bull=bull_arg, bear=bear_arg, verdict=verdict)
