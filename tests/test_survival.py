import numpy as np

from cryptoarena.agents.rules import MeanReversionAgent, MomentumAgent
from cryptoarena.arena.survival import (Individual, SurvivalConfig, _try_clone,
                                        run_survival)
from cryptoarena.learning.memory import TradeJournal


def _events(journal, event=None):
    q = "SELECT day, agent_id, event, equity, parent_id, generation FROM survival_events"
    args = ()
    if event:
        q += " WHERE event = ?"
        args = (event,)
    return journal._conn.execute(q + " ORDER BY id", args).fetchall()


def test_founders_are_born_with_the_budget(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    founders = [MomentumAgent("momentum-1", 10_000.0), MeanReversionAgent("meanrev-1", 10_000.0)]
    res = run_survival(founders, journal, SurvivalConfig(days=2, budget=500.0, seed=1),
                       verbose=False)
    born = _events(journal, "born")
    assert [(r[1], r[3]) for r in born] == [("momentum-1", 500.0), ("meanrev-1", 500.0)]
    assert all(i.budget == 500.0 for i in res.population[:2])
    assert len(res.alive_per_day) == 2
    journal.close()


def test_wallets_persist_across_days(tmp_path):
    """Unlike tournaments, survival never resets the wallet: day 2 opens
    where day 1 closed."""
    journal = TradeJournal(tmp_path / "s.db")
    run_survival([MomentumAgent("momentum-1", 10_000.0)], journal,
                 SurvivalConfig(days=3, budget=1_000.0, seed=3), verbose=False)
    rows = journal._conn.execute(
        "SELECT episode, start_equity, end_equity FROM episode_summary "
        "WHERE agent_id='momentum-1' ORDER BY episode").fetchall()
    assert len(rows) == 3
    for (_, _, end_prev), (_, start_next, _) in zip(rows, rows[1:]):
        # the market moves one bar overnight, so allow price drift but no reset
        assert abs(start_next - end_prev) / end_prev < 0.03
        assert start_next != 1_000.0
    journal.close()


def test_death_below_threshold_removes_agent(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    # death line above the budget: any day that isn't a big gain kills instantly
    res = run_survival([MomentumAgent("momentum-1", 10_000.0)], journal,
                       SurvivalConfig(days=5, budget=1_000.0, death_below=1.5, seed=2),
                       verbose=False)
    died = _events(journal, "died")
    assert len(died) == 1 and died[0][1] == "momentum-1" and died[0][0] == 1
    assert res.alive == [] and res.alive_per_day == [0]
    journal.close()


def _parent(journal, cash: float) -> Individual:
    agent = MomentumAgent("momentum-1", 1_000.0)
    agent.wallet.cash = cash
    journal.add_lesson("momentum-1", 1, "day 1: hit 3 stop-losses — entries are too aggressive.")
    return Individual(agent, "momentum", 1_000.0, None, 0, born_day=0)


def test_clone_is_paid_from_parent_surplus_and_inherits(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    parent = _parent(journal, cash=1_800.0)
    cfg = SurvivalConfig(budget=1_000.0)
    counter = iter(range(2, 10))
    child = _try_clone(parent, 4, 1_800.0, cfg, np.random.default_rng(0), journal,
                       lambda prefix: f"{prefix}-{next(counter)}", population_size=1)

    assert child is not None
    assert child.agent_id == "momentum-2"
    assert child.budget == 800.0                       # min(budget, surplus)
    assert parent.agent.wallet.cash == 1_000.0         # parent paid for it
    assert child.agent.wallet.cash == 800.0
    assert child.generation == 1 and child.parent_id == "momentum-1"
    assert child.agent.get_params() != parent.agent.get_params()   # mutated
    assert any("stop-losses" in l for l in journal.lessons_for("momentum-2"))  # inherited
    events = [(r[1], r[2], r[4]) for r in _events(journal)]
    assert ("momentum-1", "cloned", None) in events
    assert ("momentum-2", "born", "momentum-1") in events
    journal.close()


def test_clone_refused_without_surplus_or_room(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    cfg = SurvivalConfig(budget=1_000.0, max_population=3, min_clone_budget=0.25)
    rng = np.random.default_rng(0)
    ids = lambda prefix: f"{prefix}-9"  # noqa: E731

    poor = _parent(journal, cash=1_100.0)   # profit 100 < 25% of budget
    assert _try_clone(poor, 1, 1_100.0, cfg, rng, journal, ids, population_size=1) is None
    assert poor.agent.wallet.cash == 1_100.0

    invested = _parent(journal, cash=50.0)  # profitable on paper, but no cash to pay
    assert _try_clone(invested, 1, 1_600.0, cfg, rng, journal, ids, population_size=1) is None

    rich = _parent(journal, cash=3_000.0)
    assert _try_clone(rich, 1, 3_000.0, cfg, rng, journal, ids, population_size=3) is None
    assert _events(journal, "born") == []
    journal.close()


def test_intern_who_missed_target_learns_mentor_tip(tmp_path):
    from cryptoarena.arena.survival import _consult_mentor
    journal = TradeJournal(tmp_path / "s.db")
    senior = Individual(MomentumAgent("momentum-1", 1_000.0), "momentum", 1_000.0, None, 0, 0)
    other = Individual(MeanReversionAgent("meanrev-1", 1_000.0), "meanreversion", 1_000.0,
                       None, 0, 0, streak=5)
    intern = Individual(MomentumAgent("momentum-2", 200.0), "momentum", 200.0, "momentum-1", 1, 3)
    journal.add_lesson("momentum-1", 2, "day 2: barely traded — too passive; loosen entries.")
    journal.add_lesson("meanrev-1", 2, "day 2: hit 3 stop-losses — entries are too aggressive.")

    assert _consult_mentor(senior, 4, [senior, other, intern], journal) is None  # founders don't ask
    mentor = _consult_mentor(intern, 4, [senior, other, intern], journal)
    assert mentor == "momentum-1"                      # parent wins over the streaky stranger
    got = journal.lessons_for("momentum-2")
    assert got and got[-1].startswith("tip from momentum-1:") and "too passive" in got[-1]
    events = [(r[1], r[2], r[4]) for r in _events(journal, "consulted")]
    assert events == [("momentum-2", "consulted", "momentum-1")]
    journal.close()


def test_daily_cost_is_charged_and_can_kill(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    res = run_survival([MomentumAgent("momentum-1", 10_000.0)], journal,
                       SurvivalConfig(days=10, budget=1_000.0, daily_cost=0.10,
                                      death_below=0.5, seed=4), verbose=False)
    survived = _events(journal, "survived")
    assert survived and survived[0][3] < 1_000.0 * 0.95   # first day already paid rent
    assert res.alive == [] and _events(journal, "died")   # 10%/day starves it
    journal.close()


def test_clone_mutation_is_seeded():
    parent = MomentumAgent("momentum-1", 1_000.0)
    a = parent.clone("momentum-2", 500.0, np.random.default_rng(0)).get_params()
    b = parent.clone("momentum-3", 500.0, np.random.default_rng(0)).get_params()
    assert a == b and a != parent.get_params()
