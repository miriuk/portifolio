"""The real-money scorecard: four criteria agreed before the results, a
clock that starts again whenever the floor's rules change, and the
practice mirror's runs logged as counts and ratios."""
import pytest

from cryptoarena.agents.rules import MomentumAgent, ParamAgent
from cryptoarena.arena import readiness as rd
from cryptoarena.arena.chief import ChiefPolicy, report, sync_issues
from cryptoarena.arena.live_colony import POLICY_PARAMS, LiveColony
from cryptoarena.arena.readiness import ReadinessPolicy, fingerprint, scorecard, summary_line
from cryptoarena.broker.mirror import Step, summarize
from cryptoarena.cli import build_agents
from cryptoarena.floors import FLOORS
from cryptoarena.learning.memory import TradeJournal

from test_chief import QUIET, FakeGitHub, status
from test_live_colony import HOUR, T0, FakeClient, cfg, make_feed

POLICY = ReadinessPolicy(benchmark="SPY", min_days=5, ideal_days=10, max_tracking=0.05,
                         min_mirror_nights=3)
DAY = 86400
START = 12 * DAY                                  # a UTC midnight


def ledger(colony, spy, founding=None, t0=START):
    founding = founding or [colony[0]] * len(colony)
    return [[t0 + i * DAY, c, f, s] for i, (c, f, s) in enumerate(zip(colony, founding, spy))]


def runs(n, ok=True, tracking=0.0, t0=START):
    """One run a night, at 01:30."""
    return [{"ts": t0 + i * DAY + 5400, "ok": ok, "problems": 0 if ok else 1, "missed": False,
             "tracking": tracking, "unlisted": 0.4} for i in range(n)]


# ------------------------------------------------------------------ the criteria
def test_nothing_yet_is_nothing_met():
    card = scorecard([], None, [], POLICY)
    assert card["met"] == 0 and not card["ready"]
    assert [c["met"] for c in card["criteria"]] == [False, None, None, None]
    assert "0 de 4" in summary_line(card) and "⏳" in summary_line(card)


def test_every_criterion_met_is_ready():
    # six sessions after the baseline: the colony up 6% with a 1% dip, SPY up 3% with a 2% dip
    card = scorecard(ledger([100, 101, 100, 102, 104, 105, 106], [50, 49, 50, 51, 51, 51, 51.5]),
                     START, runs(3), POLICY)
    assert card["days"] == 6
    assert [c["met"] for c in card["criteria"]] == [True, True, True, True]
    assert card["ready"] and card["colony_return"] == pytest.approx(0.06)
    assert card["benchmark_return"] == pytest.approx(0.03)
    assert "40% da carteira só no papel" in card["criteria"][3]["value"]


def test_behind_or_falling_deeper_than_the_benchmark_is_not_ready():
    behind = scorecard(ledger([100] * 7, [50, 50, 50, 50, 50, 50, 51]), START, runs(3), POLICY)
    assert behind["criteria"][1]["met"] is False and not behind["ready"]
    deeper = scorecard(ledger([100, 90, 95, 100, 105, 108, 110], [50, 49, 50, 51, 51, 51, 51]),
                       START, runs(3), POLICY)
    assert deeper["criteria"][1]["met"] is True and deeper["criteria"][2]["met"] is False


def test_money_added_is_not_return():
    # a hire on day 3 brings 50 of fresh money: the colony itself was flat
    card = scorecard(ledger([100, 100, 150, 150, 150, 150], [50] * 5 + [51],
                            founding=[100, 100, 150, 150, 150, 150]), START, runs(3), POLICY)
    assert card["colony_return"] == pytest.approx(0.0)


def test_only_sessions_under_the_current_rules_count():
    rows = ledger([100, 50, 100, 101, 102, 103, 104, 105], [50] * 8)
    card = scorecard(rows, rows[2][0], runs(8), POLICY)
    assert card["days"] == 5                              # from the third row, the baseline
    assert card["colony_return"] == pytest.approx(0.05)  # the crash before it is not counted


def test_the_mirror_needs_enough_nights_no_incident_and_close_tracking():
    rows = ledger([100, 101, 102, 103, 104, 105], [50, 50, 50, 50, 50, 50])
    assert scorecard(rows, START, runs(2), POLICY)["criteria"][3]["met"] is None
    trouble = runs(3)
    trouble[1].update(ok=False, problems=1)
    assert scorecard(rows, START, trouble, POLICY)["criteria"][3]["met"] is False
    loose = scorecard(rows, START, runs(3, tracking=0.08), POLICY)
    assert loose["criteria"][3]["met"] is False and "8.0%" in loose["criteria"][3]["value"]


def test_the_retry_and_reruns_fold_into_their_night():
    rows = ledger([100, 101, 102, 103, 104, 105], [50] * 6)
    nightly = runs(3, tracking=0.08)
    # the 05:30 retry and a rerun at noon the same days, everything already in line
    again = [{**m, "ts": m["ts"] + 4 * 3600, "tracking": 0.0} for m in nightly] + \
            [{**m, "ts": m["ts"] + 10 * 3600, "tracking": 0.0} for m in nightly]
    card = scorecard(rows, START, nightly + again, POLICY)
    assert card["criteria"][3]["met"] is False                  # 8%, not diluted to 2.7%
    assert card["criteria"][3]["value"].startswith("3 noites do espelho (3 medidas)")
    # two runs a night do not make a night count twice towards the minimum
    two = runs(1) + [{**runs(1)[0], "ts": runs(1)[0]["ts"] + 4 * 3600}]
    assert scorecard(rows, START, two, POLICY)["criteria"][3]["met"] is None


def test_a_night_runs_from_one_market_open_to_the_next_and_keeps_its_worst_sample():
    rows = ledger([100, 101, 102, 103, 104, 105], [50] * 6)
    policy = ReadinessPolicy(benchmark="SPY", min_days=5, min_mirror_nights=2)
    wed = START + 2 * DAY
    log = [
        {"ts": wed + 5400, "problems": 0, "tracking": 0.0},             # Wed 01:30: Tuesday's open
        {"ts": wed + 5 * 3600 + 1800, "problems": 0, "tracking": None},  # Wed 05:30: orders queued
        # Wed 16:00, a rerun by hand after the open: an order rejected at Wednesday's open
        {"ts": wed + 16 * 3600, "problems": 0, "tracking": 0.2857},
        {"ts": wed + DAY + 5400, "problems": 0, "tracking": 0.0},       # Thu 01:30: already re-sent
    ]
    card = scorecard(rows, START, log, policy)
    assert card["criteria"][3]["value"].startswith("2 noites do espelho (2 medidas)")
    assert "14.3%" in card["criteria"][3]["value"]          # (0 + 0.2857) / 2: not thrown away
    # a Monday-afternoon rerun and Tuesday's 01:30 measure the same open: one night
    mon = START + 7 * DAY
    twice = [{"ts": mon + 16 * 3600, "problems": 0, "tracking": 0.0},
             {"ts": mon + DAY + 5400, "problems": 0, "tracking": 0.0}]
    assert scorecard(rows, START, twice, policy)["criteria"][3]["met"] is None


def test_an_unreadable_account_is_a_missed_night_judged_as_a_share():
    rows = ledger([100, 101, 102, 103, 104, 105], [50] * 6)
    policy = ReadinessPolicy(benchmark="SPY", min_days=5, min_mirror_nights=10, max_missed=0.1)
    missed = {"problems": 0, "missed": True, "tracking": None, "unlisted": None}
    one = runs(10) + [{**missed, "ts": START + 20 * DAY}]
    assert scorecard(rows, START, one, policy)["criteria"][3]["met"] is True   # 1 of 11
    three = runs(10) + [{**missed, "ts": START + (20 + i) * DAY} for i in range(3)]
    card = scorecard(rows, START, three, policy)
    assert card["criteria"][3]["met"] is False and "3 sem conseguir ler a conta" in \
        card["criteria"][3]["value"]
    # a retry that reads the account the same night saves it
    saved = runs(10) + [{**missed, "ts": START + 20 * DAY},
                        {**runs(1)[0], "ts": START + 20 * DAY + 4 * 3600}]
    assert "sem conseguir" not in scorecard(rows, START, saved, policy)["criteria"][3]["value"]


def test_the_stocks_floor_agreed_on_six_months_against_spy():
    p = FLOORS["stocks"].readiness
    assert (p.benchmark, p.min_days, p.ideal_days) == ("SPY", 126, 252)
    assert FLOORS["crypto"].readiness is None            # the crypto floor is paused


# ------------------------------------------------------------------ the fingerprint
def test_the_fingerprint_ignores_the_run_and_sees_the_rules():
    floor = FLOORS["stocks"]
    base = fingerprint(floor.config(), floor.build_founders(100.0), POLICY_PARAMS)
    # another deposit, another horizon, another seed: the same rules
    assert fingerprint(floor.config(budget=3.0, days=9, seed=7), floor.build_founders(3.0),
                       POLICY_PARAMS) == base
    assert fingerprint(floor.config(desk_symbol_cap=0.3), floor.build_founders(100.0),
                       POLICY_PARAMS) != base                                   # the desk
    tighter = floor.build_founders(100.0)
    tighter[0].set_params({"risk_stop": 0.12})
    assert fingerprint(floor.config(), tighter, POLICY_PARAMS) != base          # a seatbelt
    assert fingerprint(floor.config(), floor.build_founders(100.0)[:-1],
                       POLICY_PARAMS) != base                                   # who is on the floor
    # a parameter the floor does not impose on a running agent changes nothing
    tuned = floor.build_founders(100.0)
    tuned[0].set_params({"lookback": 21})
    assert fingerprint(floor.config(), tuned, POLICY_PARAMS) == base


def test_the_config_is_compared_with_the_snapshot_the_clock_started_with():
    floor = FLOORS["stocks"]
    cfg_ = floor.config()
    snapshot = rd.rules_config(cfg_)
    assert rd.rules_config(cfg_, snapshot) == snapshot          # nothing changed
    # a snapshot taken before an option existed: the option at its default changes nothing
    older = {k: v for k, v in snapshot.items() if k != "pm_weighting"}
    assert rd.rules_config(cfg_, older) == older
    assert rd.rules_config(floor.config(pm_weighting="hrp"), older) != older
    # a field the floor never set, whose value moved (a new default the tick copies in)
    moved = floor.config(desk_gross_cap=0.8)
    assert rd.rules_config(moved, snapshot) != snapshot


def test_the_sources_and_the_policy_are_part_of_the_rules():
    floor = FLOORS["stocks"]
    founders = floor.build_founders(100.0)
    base = fingerprint(floor.config(), founders, POLICY_PARAMS, floor.sources, floor.readiness)
    assert fingerprint(floor.config(), founders, POLICY_PARAMS, [], floor.readiness) != base
    louder = [type(s)(**{**s.__dict__, "prior": 0.5}) for s in floor.sources]
    assert fingerprint(floor.config(), founders, POLICY_PARAMS, louder, floor.readiness) != base
    qqq = ReadinessPolicy(benchmark="QQQ")
    assert fingerprint(floor.config(), founders, POLICY_PARAMS, floor.sources, qqq) != base


def _twin_a():
    class Twin(ParamAgent):
        """One docstring."""

        def act(self, view):  # a comment
            return []
    return Twin


def _twin_b():
    class Twin(ParamAgent):
        """Another docstring: the same code."""

        def act(self, view):
            # another comment
            return []
    return Twin


def _twin_c():
    class Twin(ParamAgent):
        def act(self, view):
            return [view]
    return Twin


def test_the_strategy_code_counts_its_comments_do_not(monkeypatch):
    monkeypatch.setattr(rd, "_OWN", ("cryptoarena", __name__))
    a, b, c = rd._code(_twin_a()), rd._code(_twin_b()), rd._code(_twin_c())
    assert a == b and a != c
    assert rd._code(MomentumAgent) == rd._code(MomentumAgent)


# ------------------------------------------------------------------ the live colony
def _open(path, client, founders, readiness=POLICY):
    return LiveColony.open(TradeJournal(path), founders, cfg(), make_feed(client), warmup=100,
                           verbose=False, readiness=readiness)


def test_the_live_colony_keeps_the_ledger_and_restarts_the_clock_on_new_rules(tmp_path):
    policy = ReadinessPolicy(benchmark="BTCUSD", min_days=2, min_mirror_nights=1)
    client = FakeClient()
    client.now = T0 + 120 * HOUR                     # the first closed bar ends day 1
    db = tmp_path / "live.db"
    colony = _open(db, client, build_agents(5.0, False, ""), policy)
    fp = colony.rules["fingerprint"]
    assert len(colony.ledger) == 1 and colony.rules["since"] == colony.ledger[0][0]
    assert colony.ledger[0][0] == client.now        # the session closed at midnight
    colony.journal.close()

    for _ in range(2):                               # two more days, the same rules
        client.now += 24 * HOUR
        colony = _open(db, client, build_agents(5.0, False, ""), policy)
        assert colony.rules["fingerprint"] == fp
        colony.run_once()
        card = colony.status()["go_live"]
        colony.journal.close()
    assert len(colony.ledger) == 3
    assert card["days"] == 2 and card["criteria"][0]["met"] is True
    assert card["fingerprint"] == fp

    # the floor gives everyone a tighter seatbelt: the clock starts again from the last close
    tighter = build_agents(5.0, False, "")
    for agent in tighter:
        agent.set_params({"risk_stop": 0.05})
    client.now += 24 * HOUR
    colony = _open(db, client, tighter, policy)
    assert colony.rules["fingerprint"] != fp
    assert len(colony.ledger) == 1                   # the baseline: yesterday's close
    assert colony.rules["since"] == colony.ledger[0][0]
    events = colony.journal._conn.execute(
        "SELECT day, detail FROM survival_events WHERE event = 'rules_changed'").fetchall()
    assert len(events) == 2 and "recomeça" in events[-1][1]   # the first start, then the restart
    colony.run_once()
    card = colony.status()["go_live"]
    assert card["days"] == 1 and card["criteria"][0]["met"] is False
    note = colony.chief_note() if colony.chief else None
    assert note is None                              # no chief on this colony
    colony.journal.close()


def test_a_bare_resume_and_a_floor_without_a_policy_touch_nothing(tmp_path):
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    db = tmp_path / "live.db"
    colony = _open(db, client, build_agents(5.0, False, ""), None)
    assert colony.rules is None and colony.ledger == [] and colony.status()["go_live"] is None
    colony.journal.close()
    with_policy = _open(db, client, build_agents(5.0, False, ""))
    rules = dict(with_policy.rules)
    with_policy.journal.close()
    bare = _open(db, client, [], POLICY)             # status, dashboard: no founders given
    assert bare.rules == rules
    bare.journal.close()


def test_the_mirror_runs_count_from_the_moment_the_rules_took_over(tmp_path, monkeypatch):
    policy = ReadinessPolicy(benchmark="BTCUSD", min_days=1, min_mirror_nights=1)
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    db = tmp_path / "live.db"
    journal = TradeJournal(db)
    journal.record_mirror_run(1, {"orders": 1, "problems": 1, "tracking": None, "aim": {"X": 1}})
    journal.close()
    colony = _open(db, client, build_agents(5.0, False, ""), policy)
    colony.journal.record_mirror_run(colony.rules["at"] + 60,
                                     {"orders": 2, "problems": 0, "tracking": 0.01, "aim": {"X": 1}})
    card = colony.go_live()
    assert card["criteria"][3]["met"] is True        # the old incident is not this period's
    colony.journal.close()


# ------------------------------------------------------------------ the mirror's log
def test_a_mirror_run_is_counts_and_ratios():
    prices = {"AAPL": 200.0, "NVDA": 100.0, "SPY": 500.0}
    steps = [Step("SPY", "missing", {"colony_shares": 2.0}),
             Step("AAPL", "buy", {"ticker": "AAPL_US_EQ", "quantity": 1.0, "want": 3.0, "have": 2.0}),
             Step("NVDA", "error", {"ticker": "NVDA_US_EQ", "quantity": 2.0, "want": 2.0,
                                    "have": 0.0, "error": "x"})]
    first = summarize(steps, prices, None)
    assert first["tracking"] is None and first["orders"] == 1 and first["problems"] == 1
    assert first["aim"] == {"AAPL": 3.0, "NVDA": 2.0}
    assert first["unlisted"] == pytest.approx(1000 / (600 + 200 + 1000))
    # the next night the account holds all the AAPL aimed at but none of the NVDA
    nxt = [Step("AAPL", "hold", {"shares": 3.0, "want": 3.0, "have": 3.0}),
           Step("NVDA", "buy", {"ticker": "NVDA_US_EQ", "quantity": 2.0, "want": 2.0, "have": 0.0})]
    run = summarize(nxt, prices, first["aim"])
    assert run["tracking"] == pytest.approx(200 / 800) and run["problems"] == 0
    # the 05:30 retry: the 01:30 orders wait for the open, nothing to judge yet
    waiting = [Step("AAPL", "hold", {"shares": 3.0, "want": 3.0, "have": 3.0, "queued": 0.0}),
               Step("NVDA", "hold", {"shares": 2.0, "want": 2.0, "have": 2.0, "queued": 2.0})]
    assert summarize(waiting, prices, run["aim"])["tracking"] is None


def test_the_journal_keeps_the_runs_and_the_last_aim(tmp_path):
    journal = TradeJournal(tmp_path / "j.db")
    assert journal.last_mirror_aim() is None
    journal.record_mirror_run(10, {"orders": 2, "problems": 0, "tracking": None, "unlisted": 0.5,
                                   "aim": {"AAPL": 1.5}})
    journal.record_mirror_run(20, {"orders": 0, "problems": 0, "missed": 1, "tracking": None,
                                   "aim": {}})
    assert journal.last_mirror_aim() == {"AAPL": 1.5}       # a run that never read the account
    got = journal.mirror_runs(since=15)
    assert [(r["ts"], r["ok"], r["problems"], r["missed"]) for r in got] == [(20, False, 0, True)]
    journal.close()


def test_the_cli_logs_an_executed_run_but_not_a_rehearsal(tmp_path, monkeypatch, capsys):
    from cryptoarena import cli
    from cryptoarena.broker import trading212
    from test_mirror import FakeDemo

    db = tmp_path / "stocks.db"
    journal = TradeJournal(db)
    journal.save_state("live_colony", {
        "symbols": ["SPY", "AAPL"], "last_prices": {"SPY": 500.0, "AAPL": 200.0},
        "population": [{"died_day": None, "agent": {"wallet": {"positions": {"AAPL": 2.0,
                                                                               "SPY": 1.0}}}}]})
    journal.close()
    fake = FakeDemo()
    monkeypatch.setattr(trading212.PracticeAccount, "from_env",
                        classmethod(lambda cls, env=None: cls("k", "s", opener=fake,
                                                              sleep=lambda s: None)))
    monkeypatch.setattr("sys.argv", ["cryptoarena", "t212", "mirror", "--db", str(db)])
    cli.main()
    journal = TradeJournal(db)
    assert journal.mirror_runs() == []                       # a rehearsal is not a run
    journal.close()
    monkeypatch.setattr("sys.argv", ["cryptoarena", "t212", "mirror", "--db", str(db), "--execute"])
    cli.main()
    cli.main()                                               # the next night: already in line
    journal = TradeJournal(db)
    got = journal.mirror_runs()
    journal.close()
    assert [r["orders"] for r in got] == [1, 0]
    assert got[0]["tracking"] is None and got[1]["tracking"] == pytest.approx(0.0)
    assert got[0]["aim"] == {"AAPL": 2.0} and got[0]["unlisted"] == pytest.approx(500 / 900)
    assert "readiness log" in capsys.readouterr().out
    # the account cannot be read: the night is logged as missed, not as an incident
    def down(req, timeout=None):
        raise OSError("connection reset")
    monkeypatch.setattr(trading212.PracticeAccount, "from_env",
                        classmethod(lambda cls, env=None: cls("k", "s", opener=down,
                                                              sleep=lambda s: None)))
    with pytest.raises(Exception):
        cli.main()
    journal = TradeJournal(db)
    last = journal.mirror_runs()[-1]
    journal.close()
    assert last["missed"] and last["problems"] == 0 and last["orders"] == 0


def test_a_read_is_tried_again_after_a_passing_failure_and_an_order_never_is():
    import io
    import urllib.error
    from cryptoarena.broker.trading212 import OrderUncertain, PracticeAccount
    calls = []

    def flaky(req, timeout=None):
        calls.append(req.get_method())
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, io.BytesIO(b""))
        if req.get_method() == "POST":
            raise urllib.error.URLError("reset")
        return io.BytesIO(b"[]")

    acc = PracticeAccount("k", "s", opener=flaky, sleep=lambda s: None)
    assert acc.positions() == [] and calls == ["GET", "GET"]
    with pytest.raises(OrderUncertain):
        acc.market_order("AAPL_US_EQ", 1.0)
    assert calls.count("POST") == 1                          # sent once, never again


def test_a_read_cut_off_mid_body_is_retried_then_a_missed_night_and_after_an_order_uncertain():
    import http.client
    from cryptoarena.broker.mirror import AccountUnreadable, mirror
    from cryptoarena.broker.trading212 import OrderUncertain, PracticeAccount

    class Cut:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"[{", 4_000_000)

    gets = []

    def cut_once(req, timeout=None):
        gets.append(req.get_method())
        return Cut() if len(gets) == 1 else __import__("io").BytesIO(b"[]")

    assert PracticeAccount("k", "s", opener=cut_once, sleep=lambda s: None).positions() == []
    assert gets == ["GET", "GET"]
    always = PracticeAccount("k", "s", opener=lambda req, timeout=None: Cut(), sleep=lambda s: None)
    with pytest.raises(AccountUnreadable):
        mirror(always, {"AAPL": 1.0}, ["AAPL"], execute=True)
    with pytest.raises(OrderUncertain):
        always.market_order("AAPL_US_EQ", 1.0)


# ------------------------------------------------------------------ the chief
def test_the_chief_carries_the_line_and_calls_the_owner_only_when_all_are_met():
    policy = ChiefPolicy(benchmark="SPY", min_days=10)
    ready = scorecard(ledger([100, 101, 102, 103, 104, 105, 106], [50] * 6 + [51]),
                      START, runs(3), POLICY)
    ready["rules_day"] = 4
    note = report(status(1010.0, 101.0), QUIET, {"price": 100.0}, 1000.0, policy,
                  now=1_790_000_000.0, readiness=ready)
    assert any(line.startswith("Prontidão para dinheiro real: 4 de 4") for line in note["lines"])
    assert [d["key"] for d in note["decisions"]] == ["ready"]
    assert "nunca opera dinheiro real" in note["decisions"][0]["body"]
    gh = FakeGitHub()
    assert sync_issues(gh, "stocks", note)[0].startswith("opened #1")
    not_yet = scorecard(ledger([100, 101], [50, 51]), START, [], POLICY)
    later = report(status(1010.0, 101.0, day=13), QUIET, {"price": 100.0}, 1000.0, policy,
                   now=1_790_000_000.0, readiness=not_yet)
    assert later["decisions"] == []
    assert sync_issues(gh, "stocks", later) == ["closed #1"]     # a criterion slipped: it closes


def test_a_change_of_rules_gets_a_line_in_the_note():
    activity = {**QUIET, "events": [("chief", "rules_changed", "regras a → b: o relógio recomeça")]}
    note = report(status(1010.0, 101.0), activity, {"price": 100.0}, 1000.0,
                  ChiefPolicy(benchmark="SPY"), now=1_790_000_000.0)
    assert any("Mudança nas regras do andar" in line for line in note["lines"])


def test_a_quiet_source_coming_alive_starts_the_clock_again(monkeypatch):
    floor = FLOORS["stocks"]
    founders = floor.build_founders(100.0)
    quiet = fingerprint(floor.config(), founders, POLICY_PARAMS, floor.sources, floor.readiness,
                        quiet=("sec-form4",))
    alive = fingerprint(floor.config(), founders, POLICY_PARAMS, floor.sources, floor.readiness)
    assert quiet != alive


def test_the_live_colony_sees_whether_sec_form4_can_read(tmp_path, monkeypatch):
    from cryptoarena.market.sources import Source
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    colony = _open(tmp_path / "q.db", client, build_agents(5.0, False, ""))
    colony.sources = [Source("sec-form4")]
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert colony._quiet_sources() == ("sec-form4",)
    monkeypatch.setenv("SEC_USER_AGENT", "Owner owner@example.org")
    assert colony._quiet_sources() == ()
    colony.journal.close()


def test_a_failed_order_keeps_the_brokers_code_and_never_its_text(tmp_path):
    from cryptoarena.broker.mirror import _reason
    from cryptoarena.broker.trading212 import T212Error
    exc = T212Error(400, '{"code": "InstrumentNotAvailable", "clarification": "free 1234.56 GBP"}')
    assert _reason(exc) == "HTTP 400 InstrumentNotAvailable"
    steps = [Step("QQQ", "error", {"ticker": "QQQ_US_EQ", "quantity": 0.04, "want": 0.18,
                                   "have": 0.13, "queued": 0.0, "error": str(exc),
                                   "reason": _reason(exc)})]
    run = summarize(steps, {"QQQ": 745.0}, None)
    assert run["reasons"] == ["QQQ error: HTTP 400 InstrumentNotAvailable"]
    journal = TradeJournal(tmp_path / "r.db")
    journal.record_mirror_run(5, run)
    got = journal.mirror_runs()[0]
    journal.close()
    assert got["reasons"] == run["reasons"] and "1234" not in str(got)
