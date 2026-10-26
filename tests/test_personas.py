"""Names, titles and superpowers: how each agent id is shown."""
from cryptoarena.floors import crypto_founders, stock_founders
from cryptoarena.world.personas import DESK, FOUNDERS, display, persona, roster


def test_every_founder_on_both_floors_has_its_own_persona():
    ids = {a.agent_id for a in stock_founders(1.0) + crypto_founders(1.0)}
    assert ids <= set(FOUNDERS)
    names = [persona(i).name for i in ids]
    assert len(set(names)) == len(names)                       # nobody shares a name
    assert all(persona(i).title and persona(i).power for i in ids)


def test_an_intern_is_its_founders_junior():
    assert persona("momentum-3", "momentum-2").name == "Marco Jr. 3"
    intern = persona("momentum-4")                             # parent unknown: the strategy's first
    assert intern.name == "Rita Jr. 4" and not intern.founder
    assert intern.title.startswith("Estagiário") and intern.power == FOUNDERS["momentum-1"].power
    assert persona("bear-1").name == "Bruno Urso" and persona("bear-2").name == "Bruno Jr. 2"
    assert persona("claude-trader").emoji == "🤖"
    assert persona("mystery").name == "mystery"                 # an unknown id shows as itself


def test_the_desk_and_the_short_forms():
    assert display("index-1") == "🗿 Inês Índice"
    assert FOUNDERS["momentum-1"].tag == "🏃 Rita"
    assert {k for k in DESK} == {"risk", "pm", "chief"}
    assert roster(["trend-1"])[0]["name"] == "Tomás Bússola"
