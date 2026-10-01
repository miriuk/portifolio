from types import SimpleNamespace

from cryptoarena.agents.debate import DebateVerdict, run_debate
from cryptoarena.agents.llm import ClaudeTraderAgent


class FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeMessages:
    """Mimics anthropic client.messages for create() and parse()."""

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        prompt = kwargs["messages"][0]["content"]
        role = "bull" if "Bull Analyst" in prompt.split("\n")[0] else "bear"
        return SimpleNamespace(content=[FakeBlock(f"{role} argument citing numbers")])

    def parse(self, **kwargs):
        self.calls.append(("parse", kwargs))
        return SimpleNamespace(parsed_output=DebateVerdict(
            rating="underweight", conviction=0.7,
            plan="Trim exposure. Wait for confirmation."))


def fake_client():
    return SimpleNamespace(messages=FakeMessages())


def test_debate_runs_bull_bear_judge():
    client = fake_client()
    result = run_debate(client, "model-x", market="BTC flat", lessons="- none")
    kinds = [k for k, _ in client.messages.calls]
    assert kinds == ["create", "create", "parse"]  # bull, bear, judge
    assert "bull" in result.bull and "bear" in result.bear
    assert result.verdict.rating == "underweight"
    # bear saw the bull's argument; judge saw the whole transcript
    bear_prompt = client.messages.calls[1][1]["messages"][0]["content"]
    assert "bull argument" in bear_prompt
    judge_prompt = client.messages.calls[2][1]["messages"][0]["content"]
    assert "Bull Analyst:" in judge_prompt and "Bear Analyst:" in judge_prompt


def test_multi_round_debate():
    client = fake_client()
    run_debate(client, "model-x", market="m", lessons="l", rounds=2)
    kinds = [k for k, _ in client.messages.calls]
    assert kinds == ["create", "create", "create", "create", "parse"]


def test_agent_injects_verdict_into_decision_prompt():
    class DecisionMessages(FakeMessages):
        def parse(self, **kwargs):
            self.calls.append(("parse", kwargs))
            prompt = kwargs["messages"][0]["content"]
            if "output_format" in kwargs and kwargs["output_format"] is DebateVerdict:
                return SimpleNamespace(parsed_output=DebateVerdict(
                    rating="sell", conviction=0.9, plan="Exit now."))
            # trader decision call: must contain the judge's rating
            assert "Judge's rating: sell" in prompt
            from cryptoarena.agents.llm import DecisionSet
            return SimpleNamespace(parsed_output=DecisionSet(
                market_read="bearish", decisions=[]))

    client = SimpleNamespace(messages=DecisionMessages())
    agent = ClaudeTraderAgent("t", client=client, debate=True, decision_interval=1)
    # feed enough history for indicators
    from cryptoarena.market.candle import Candle
    from cryptoarena.agents.base import MarketView
    candles = [Candle("BTCUSDT", i, 100.0, 101.0, 99.0, 100.0, 10.0) for i in range(80)]
    for c in candles:
        agent.observe([c])
    view = MarketView(candles={"BTCUSDT": candles[-1]},
                      history=agent.history, prices={"BTCUSDT": 100.0}, step=80)
    orders = agent.decide(view)
    assert orders == []               # trader followed the empty decision set
    assert agent.last_debate is not None
    assert agent.last_debate.verdict.rating == "sell"
