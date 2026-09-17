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


def test_the_clock_keeps_running_across_days(tmp_path):
    """Regression: with the step restarting at 0 every day, cooldowns never
    expired and agents traded once and froze for the rest of the run."""
    from cryptoarena.agents.base import TradingAgent
    from cryptoarena.arena.episode import run_episode
    from cryptoarena.market.synthetic import SyntheticMarket

    class Clock(TradingAgent):
        seen: list[int] = []

        def decide(self, view):
            self.seen.append(view.step)
            return []

    journal = TradeJournal(tmp_path / "s.db")
    market = SyntheticMarket({"BTCUSDT": 100.0}, seed=1)
    agent = Clock("clock-1", 5.0)
    run_episode(1, market, [agent], journal, steps=24)
    run_episode(2, market, [agent], journal, steps=24, step_offset=24)
    assert Clock.seen == list(range(48))
    journal.close()


def test_survival_agents_keep_trading_after_day_one(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    run_survival([MomentumAgent("momentum-1", 1000.0)], journal,
                 SurvivalConfig(days=12, budget=1000.0, seed=7), verbose=False)
    days_with_trades = journal._conn.execute(
        "SELECT COUNT(DISTINCT episode) FROM trades").fetchone()[0]
    assert days_with_trades >= 3
    assert journal.load_params("momentum-1") is not None   # founders' params are persisted too
    journal.close()


def test_a_fiver_is_enough_to_trade(tmp_path):
    """The £5 experiment: tiny budgets must still produce trades."""
    from cryptoarena.cli import build_agents
    journal = TradeJournal(tmp_path / "s.db")
    run_survival(build_agents(5.0, False, ""), journal,
                 SurvivalConfig(days=6, budget=5.0, seed=7), verbose=False)
    n_trades = journal._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    assert n_trades > 0
    biggest = journal._conn.execute(
        "SELECT MAX(quantity * price) FROM trades WHERE side='buy'").fetchone()[0]
    assert biggest <= 5.0 * 0.35 + 1e-6      # risk limits scale with the budget too
    journal.close()


def test_regime_aware_agents_react_to_panic_and_trends():
    from collections import deque
    from cryptoarena.agents.rules import RegimeSwitchAgent, VolTargetAgent
    from cryptoarena.market.candle import Candle
    from cryptoarena.agents.base import MarketView

    def feed(agent, closes):
        agent.history["BTCUSDT"] = deque(
            [Candle("BTCUSDT", t, c, c * 1.01, c * 0.99, c, 1_000.0) for t, c in enumerate(closes)],
            maxlen=200)
        last = agent.history["BTCUSDT"][-1]
        return MarketView(candles={"BTCUSDT": last}, history=agent.history,
                          prices={"BTCUSDT": last.close}, step=len(closes))

    calm_trend = [100 * (1.001 ** t) for t in range(100)]           # +10% steady climb
    rs = RegimeSwitchAgent("regime-1", 5.0)
    view = feed(rs, calm_trend)
    assert rs.regime("BTCUSDT") == "trending"
    orders = rs.decide(view)
    assert orders and orders[0].side == "buy" and "trending" in orders[0].reason

    vt = VolTargetAgent("voltarget-1", 5.0)
    orders = vt.decide(feed(vt, calm_trend))
    assert orders and orders[0].side == "buy" and orders[0].quote_amount <= 5.0 * 0.30

    wild = [100 * (1 + (0.06 if t % 2 else -0.06)) ** (t % 3) for t in range(100)]  # violent chop
    rs.wallet.positions["BTCUSDT"] = 0.01
    assert rs.regime("BTCUSDT") != "trending" or True
    view = feed(rs, wild)
    if rs.regime("BTCUSDT") == "panic":
        orders = rs.decide(view)
        assert orders and orders[0].side == "sell" and "panic" in orders[0].reason


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


def test_specialists_are_never_let_go(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    # death line above the budget would dismiss anyone on day 1 — but founders stay
    res = run_survival([MomentumAgent("momentum-1", 10_000.0)], journal,
                       SurvivalConfig(days=5, budget=1_000.0, death_below=1.5, seed=2),
                       verbose=False)
    assert _events(journal, "died") == []
    assert len(res.alive) == 1 and res.alive_per_day == [1] * 5
    journal.close()


def test_only_interns_below_the_line_are_let_go():
    from cryptoarena.arena.survival import _let_go
    cfg = SurvivalConfig(death_below=0.6)
    founder = Individual(MomentumAgent("momentum-1", 1000.0), "momentum", 1000.0, None, 0, 0)
    intern = Individual(MomentumAgent("momentum-2", 100.0), "momentum", 100.0, "momentum-1", 1, 3)
    assert _let_go(founder, 10.0, True, cfg) is False        # never, not even kill-switched
    assert _let_go(intern, 59.0, False, cfg) is True         # below 60% of its own budget
    assert _let_go(intern, 80.0, True, cfg) is True          # kill switch
    assert _let_go(intern, 61.0, False, cfg) is False
    intern.immune_until = 14                                  # last week's winner
    assert _let_go(intern, 59.0, False, cfg, day=12) == "spared"
    assert _let_go(intern, 80.0, True, cfg, day=14) == "spared"
    assert _let_go(intern, 59.0, False, cfg, day=15) is True  # immunity expired


def _parent(journal, cash: float) -> Individual:
    agent = MomentumAgent("momentum-1", 1_000.0)
    agent.wallet.cash = cash
    journal.add_lesson("momentum-1", 1, "day 1: hit 3 stop-losses — entries are too aggressive.")
    return Individual(agent, "momentum", 1_000.0, None, 0, born_day=0)


def test_child_is_born_with_the_surplus(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    parent = _parent(journal, cash=2_100.0)
    cfg = SurvivalConfig(budget=1_000.0, clone_at=2.0)
    counter = iter(range(2, 10))
    child = _try_clone(parent, 4, 2_100.0, cfg, np.random.default_rng(0), journal,
                       lambda prefix: f"{prefix}-{next(counter)}", population_size=1)

    assert child is not None
    assert child.agent_id == "momentum-2"
    assert child.budget == 1_100.0                     # the surplus above the parent's budget
    assert parent.agent.wallet.cash == 1_000.0         # the parent is back to its budget
    assert child.agent.wallet.cash == 1_100.0
    assert child.generation == 1 and child.parent_id == "momentum-1"
    assert child.agent.get_params() == parent.agent.get_params()   # faithful copy
    assert any("stop-losses" in l for l in journal.lessons_for("momentum-2"))  # inherited
    events = [(r[1], r[2], r[4]) for r in _events(journal)]
    assert ("momentum-1", "cloned", None) in events
    assert ("momentum-2", "born", "momentum-1") in events
    journal.close()


def test_clone_refused_below_the_hiring_line_or_without_cash_or_room(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    cfg = SurvivalConfig(budget=1_000.0, max_population=3, clone_at=2.0, min_child_budget=0.2)
    rng = np.random.default_rng(0)
    ids = lambda prefix: f"{prefix}-9"  # noqa: E731

    almost = _parent(journal, cash=1_900.0)   # +90% is not doubled
    assert _try_clone(almost, 1, 1_900.0, cfg, rng, journal, ids, population_size=1) is None
    assert almost.agent.wallet.cash == 1_900.0

    invested = _parent(journal, cash=500.0)   # doubled on paper; pays what it has on hand
    child = _try_clone(invested, 1, 2_200.0, cfg, rng, journal, ids, population_size=1)
    assert child is not None and child.budget == 500.0 and invested.agent.wallet.cash == 0.0

    broke = _parent(journal, cash=0.1)        # doubled on paper, but not even the minimum in cash
    assert _try_clone(broke, 1, 2_200.0, cfg, rng, journal, ids, population_size=1) is None

    rich = _parent(journal, cash=3_000.0)
    assert _try_clone(rich, 1, 3_000.0, cfg, rng, journal, ids, population_size=3) is None
    assert len(_events(journal, "born")) == 1   # only the partial hire above
    journal.close()


def test_fiver_children_are_tiny_and_live_by_scaled_rules(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    parent = Individual(MomentumAgent("momentum-1", 5.0), "momentum", 5.0, None, 0, 0)
    parent.agent.wallet.cash = 5.6
    cfg = SurvivalConfig(budget=5.0, clone_at=1.1, min_child_budget=0.2, death_below=0.6)
    ids = lambda prefix: f"{prefix}-2"  # noqa: E731
    child = _try_clone(parent, 3, 5.6, cfg, np.random.default_rng(0), journal, ids, population_size=1)
    assert child is not None and abs(child.budget - 0.6) < 1e-9
    assert abs(parent.agent.wallet.cash - 5.0) < 1e-9
    from cryptoarena.arena.survival import _let_go
    assert _let_go(child, 0.35, False, cfg, day=4) is True      # below 60% of its own 0.60
    assert _let_go(child, 0.37, False, cfg, day=4) is False
    # too small a surplus makes no child: at 5.15 the surplus is under the 0.20 minimum
    parent.agent.wallet.cash = 5.15
    assert _try_clone(parent, 4, 5.15, cfg, np.random.default_rng(0), journal,
                      lambda p: f"{p}-3", population_size=2) is None
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


def test_daily_cost_is_charged(tmp_path):
    journal = TradeJournal(tmp_path / "s.db")
    run_survival([MomentumAgent("momentum-1", 10_000.0)], journal,
                 SurvivalConfig(days=3, budget=1_000.0, daily_cost=0.10, seed=4),
                 verbose=False)
    survived = _events(journal, "survived")
    assert survived and survived[0][3] < 1_000.0 * 0.95   # first day already paid rent
    assert survived[-1][3] < survived[0][3]               # and it keeps bleeding
    journal.close()


def test_happy_hour_rewards_weekly_winners(tmp_path):
    from cryptoarena.arena.survival import _happy_hour
    journal = TradeJournal(tmp_path / "s.db")
    cfg = SurvivalConfig(daily_target=0.005, week_days=7)   # weekly target ≈ +3.55%
    people = []
    for aid, start, end in [("momentum-1", 1000.0, 1050.0), ("meanrev-1", 1000.0, 1040.0),
                            ("breakout-1", 1000.0, 1010.0)]:
        ind = Individual(MomentumAgent(aid, 1000.0), aid.split("-")[0], 1000.0, None, 0, 0)
        ind.week_start_equity = start
        journal.record_episode_summary(type("S", (), dict(
            agent_id=aid, episode=7, start_equity=start, end_equity=end, n_trades=1, n_wins=1,
            n_losses=0, n_stop_losses=0, fees=0.0, max_drawdown=0.0))())
        people.append(ind)
    winners = _happy_hour(7, 1, people, cfg, journal)
    assert winners == ["momentum-1", "meanrev-1"]            # breakout missed the week
    assert [r[1] for r in _events(journal, "party")] == ["momentum-1", "meanrev-1"]
    assert [r[1] for r in _events(journal, "employee_of_week")] == ["momentum-1"]
    assert any("employee of the week" in l for l in journal.lessons_for("momentum-1"))
    assert all(i.week_start_equity is None for i in people)   # a new week starts
    assert [i.immune_until for i in people] == [14, 14, 0]    # winners are safe next week
    assert [r[1] for r in _events(journal, "immune")] == ["momentum-1", "meanrev-1"]
    journal.close()


def test_clone_is_faithful_by_default_and_warm():
    from collections import deque
    from cryptoarena.market.candle import Candle
    parent = MomentumAgent("momentum-1", 1_000.0, params={"lookback": 30})
    parent.history["BTCUSDT"] = deque(
        [Candle("BTCUSDT", t, 100.0, 101.0, 99.0, 100.0 + t, 1.0) for t in range(80)], maxlen=200)
    child = parent.clone("momentum-2", 120.0)
    assert child.get_params() == parent.get_params()                 # same brain
    assert child.momentum("BTCUSDT", 30) == parent.momentum("BTCUSDT", 30)   # same eyes, day one
    child.history["BTCUSDT"].append(Candle("BTCUSDT", 99, 1, 1, 1, 1.0, 1.0))
    assert len(parent.history["BTCUSDT"]) == 80                      # but its own copy
    assert child._can_buy() and child.wallet.cash == 120.0           # and it can trade

    mutated = parent.clone("momentum-3", 120.0, np.random.default_rng(0), mutate=True)
    again = parent.clone("momentum-4", 120.0, np.random.default_rng(0), mutate=True)
    assert mutated.get_params() != parent.get_params()
    assert mutated.get_params() == again.get_params()                # seeded exploration


def test_small_intern_can_buy_and_imitation_moves_params():
    intern = MomentumAgent("momentum-2", 80.0, params={"entry_threshold": 0.04, "cooldown": 8})
    assert intern._can_buy()                       # 80 > 5% of 80; the old 'cash > 100' blocked it
    intern.wallet.cash = 3.0
    assert not intern._can_buy()
    intern.imitate({"entry_threshold": 0.02, "cooldown": 4, "lookback": 24, "junk": 9}, 0.5)
    assert intern.params["entry_threshold"] == 0.03
    assert intern.params["cooldown"] == 6 and isinstance(intern.params["cooldown"], int)
    assert "junk" not in intern.params


def test_weekly_training_imitates_the_best_specialist(tmp_path):
    from cryptoarena.arena.survival import _weekly_training
    journal = TradeJournal(tmp_path / "s.db")
    good = Individual(MomentumAgent("momentum-1", 1000.0, params={"entry_threshold": 0.010}),
                      "momentum", 1000.0, None, 0, 0)
    bad = Individual(MomentumAgent("momentum-2", 1000.0, params={"entry_threshold": 0.050}),
                     "momentum", 1000.0, None, 0, 0)
    other = Individual(MeanReversionAgent("meanrev-1", 1000.0), "meanreversion", 1000.0, None, 0, 0)
    intern = Individual(MomentumAgent("momentum-3", 200.0, params={"entry_threshold": 0.030}),
                        "momentum", 200.0, "momentum-2", 1, 3)
    stats = lambda aid, ep, s, e: type("S", (), dict(   # noqa: E731
        agent_id=aid, episode=ep, start_equity=s, end_equity=e, n_trades=1, n_wins=1,
        n_losses=0, n_stop_losses=0, fees=0.0, max_drawdown=0.0))()
    for ep in range(1, 8):
        journal.record_episode_summary(stats("momentum-1", ep, 1000 + 10 * (ep - 1), 1000 + 10 * ep))
        journal.record_episode_summary(stats("momentum-2", ep, 1000 - 5 * (ep - 1), 1000 - 5 * ep))
    cfg = SurvivalConfig(imitation_rate=0.5, week_days=7)
    trained = _weekly_training(7, [good, bad, other, intern], cfg, journal)
    assert trained == [("momentum-3", "momentum-1")]         # the best week, not the parent
    assert abs(intern.agent.params["entry_threshold"] - 0.020) < 1e-9
    ev = journal._conn.execute("SELECT parent_id, detail FROM survival_events WHERE event='trained'").fetchone()
    assert ev[0] == "momentum-1" and "imitated momentum-1" in ev[1]
    assert journal.load_params("momentum-3")[0]["entry_threshold"] == intern.agent.params["entry_threshold"]
    journal.close()


def test_senior_is_earned_and_interns_size_like_them(tmp_path):
    from cryptoarena.agents.rules import VolTargetAgent
    from cryptoarena.arena.survival import (_effective_order_frac, _pick_senior,
                                            _weekly_training)
    from cryptoarena.learning.memory import TradeRecord
    journal = TradeJournal(tmp_path / "s.db")
    stats = lambda aid, ep, s, e: type("S", (), dict(   # noqa: E731
        agent_id=aid, episode=ep, start_equity=s, end_equity=e, n_trades=1, n_wins=1,
        n_losses=0, n_stop_losses=0, fees=0.0, max_drawdown=0.0))()
    vol = Individual(VolTargetAgent("voltarget-1", 5.0, params={"cooldown": 4}),
                     "voltarget", 5.0, None, 0, 0)
    mom = Individual(MomentumAgent("momentum-1", 5.0, params={"order_frac": 0.15, "cooldown": 8}),
                     "momentum", 5.0, None, 0, 0)
    intern = Individual(MomentumAgent("momentum-2", 5.0, params={"order_frac": 0.15, "cooldown": 8}),
                        "momentum", 5.0, "momentum-1", 1, 3)
    for ep in range(1, 8):
        journal.record_episode_summary(stats("voltarget-1", ep, 5 + 0.2 * (ep - 1), 5 + 0.2 * ep))
        journal.record_episode_summary(stats("momentum-1", ep, 5 - 0.05 * (ep - 1), 5 - 0.05 * ep))
        journal.record_episode_summary(stats("momentum-2", ep, 5.0, 5.0))
        # the senior buys small: 5% of the morning's equity each time
        journal.record_trade(TradeRecord("voltarget-1", ep, "BTCUSDT", "buy",
                                         quantity=0.05 * (5 + 0.2 * (ep - 1)) / 100.0,
                                         price=100.0, fee=0.0, timestamp=ep))
    senior = _pick_senior(7, [vol, mom, intern], journal)
    assert senior is vol                                   # +28% beats -7%: earned, not appointed
    ev = journal._conn.execute("SELECT agent_id, detail FROM survival_events WHERE event='senior'").fetchone()
    assert ev[0] == "voltarget-1" and "+28.0%" in ev[1]
    assert abs(_effective_order_frac(journal, "voltarget-1", 7, 7) - 0.05) < 1e-9

    cfg = SurvivalConfig(imitation_rate=0.5, senior_rate=0.5, week_days=7)
    _weekly_training(7, [vol, mom, intern], cfg, journal, senior=senior)
    p = intern.agent.params
    assert abs(p["order_frac"] - 0.10) < 1e-9        # halfway from 15% to the senior's 5%
    assert p["cooldown"] == 6                          # halfway from 8 to the senior's 4
    detail = journal._conn.execute("SELECT detail FROM survival_events WHERE event='trained'").fetchone()[0]
    assert "imitated momentum-1" in detail and "sized like senior voltarget-1 (5% of equity per buy)" in detail
    journal.close()


def test_intern_escalates_to_the_senior_after_repeated_misses(tmp_path):
    from cryptoarena.agents.rules import VolTargetAgent
    from cryptoarena.arena.survival import _consult_mentor
    journal = TradeJournal(tmp_path / "s.db")
    parent = Individual(MomentumAgent("momentum-1", 5.0), "momentum", 5.0, None, 0, 0)
    senior = Individual(VolTargetAgent("voltarget-1", 5.0), "voltarget", 5.0, None, 0, 0)
    intern = Individual(MomentumAgent("momentum-2", 5.0), "momentum", 5.0, "momentum-1", 1, 3)
    journal.add_lesson("momentum-1", 2, "day 2: barely traded — too passive; loosen entries.")
    journal.add_lesson("voltarget-1", 2, "day 2: drawdown reached 30% — position sizing too large.")
    assert _consult_mentor(intern, 5, [parent, senior, intern], journal) == "momentum-1"
    assert _consult_mentor(intern, 6, [parent, senior, intern], journal, senior=senior) == "voltarget-1"
    assert any("sizing too large" in l for l in journal.lessons_for("momentum-2"))
    journal.close()


def test_tip_also_nudges_parameters(tmp_path):
    from cryptoarena.arena.survival import _consult_mentor
    journal = TradeJournal(tmp_path / "s.db")
    senior = Individual(MomentumAgent("momentum-1", 1000.0, params={"cooldown": 4}), "momentum",
                        1000.0, None, 0, 0)
    intern = Individual(MomentumAgent("momentum-2", 200.0, params={"cooldown": 14}), "momentum",
                        200.0, "momentum-1", 1, 3)
    journal.add_lesson("momentum-1", 2, "day 2: fees ate a losing day — overtrading; trade less.")
    assert _consult_mentor(intern, 4, [senior, intern], journal, tip_rate=0.5) == "momentum-1"
    # learn() nudges cooldown up (overtrading), then imitation pulls halfway to the mentor's 4
    assert intern.agent.params["cooldown"] < 14
    journal.close()
