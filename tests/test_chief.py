"""The chief of staff: a note every day, a call to the owner only when a
decision is needed, and one GitHub issue per standing decision."""
from cryptoarena.arena.chief import ChiefPolicy, bench_start, report, sync_issues

POLICY = ChiefPolicy(benchmark="SPY", min_days=10, behind_pts=0.03, drawdown=0.05,
                     pm_lead=0.02, stale_days=5)
QUIET = {"buys": [], "sells": [], "events": []}
NOW = 1_790_000_000.0


def status(equity, spy, day=12, pm=None, last="2026-09-20T00:00:00+00:00"):
    return {"day": day, "hour": 0, "colony_equity": equity, "prices": {"SPY": spy},
            "last_candle": last, "desk": {"pm": pm} if pm else None}


def test_a_quiet_day_is_a_note_and_nothing_to_decide():
    note = report(status(1010.0, 102.0), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert note["decisions"] == []
    assert "+1.00%" in note["lines"][0] and "+2.00%" in note["lines"][0]
    assert note["headline"] == note["lines"][0]
    assert note["day"] == 11                                   # the last closed day


def test_trailing_the_benchmark_asks_for_a_decision_only_after_min_days():
    early = report(status(1000.0, 110.0, day=5), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert early["decisions"] == []
    late = report(status(1000.0, 110.0), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert [d["key"] for d in late["decisions"]] == ["behind"]
    assert "10.0%" in late["decisions"][0]["title"]


def test_drawdown_pm_lead_and_a_stale_feed_are_decisions():
    pm = {"return": 0.01, "colony_return": -0.06, "since_day": 3}
    note = report(status(930.0, 93.0, pm=pm, last="2026-08-01T00:00:00+00:00"), QUIET,
                  {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert {d["key"] for d in note["decisions"]} == {"drawdown", "pm_ahead", "stale"}
    assert note["headline"].startswith("3 decisão(ões)")


def test_the_days_trades_and_the_desks_refusals_are_in_the_note():
    activity = {"buys": [("NVDA", 4, 146.0)], "sells": [("AAPL", 1, 36.5)],
                "events": [("trend-1", "vetoed", "desk: buy NVDA refused: NVDA at 20% of the desk")]}
    note = report(status(1000.0, 100.0), activity, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    text = " ".join(note["lines"])
    assert "comprou NVDA (4× $146.00)" in text and "vendeu AAPL" in text
    assert "barrou ou cortou 1" in text and "trend-1" in text


def test_the_benchmark_starts_at_the_founding_bar():
    tape = {"SPY": [[100, 0, 0, 0, 10.0, 0], [200, 0, 0, 0, 11.0, 0], [300, 0, 0, 0, 12.0, 0]]}
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(200, tz=timezone.utc).isoformat()
    assert bench_start(tape, "SPY", start) == {"symbol": "SPY", "ts": 200, "price": 11.0}


class FakeGitHub:
    def __init__(self):
        self.issues, self.log = {}, []

    def open_issues(self):
        return [i for i in self.issues.values() if i["state"] == "open"]

    def create(self, title, body):
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "title": title, "body": body, "state": "open"}
        self.log.append(("create", n))
        return self.issues[n]

    def edit(self, number, **fields):
        self.issues[number].update(fields)
        self.log.append(("edit", number))

    def comment(self, number, body):
        self.log.append(("comment", number))


def test_one_issue_per_decision_kept_current_then_closed_when_it_clears():
    gh = FakeGitHub()
    behind = report(status(1000.0, 110.0), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    sync_issues(gh, "stocks", behind)
    assert len(gh.issues) == 1 and gh.issues[1]["title"].startswith("[stocks] A colônia")
    assert sync_issues(gh, "stocks", behind) == []             # same day again: nothing to do
    later = report(status(1000.0, 111.0, day=13), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert sync_issues(gh, "stocks", later) == ["updated #1"]  # still standing: body refreshed
    assert len(gh.issues) == 1
    fine = report(status(1100.0, 101.0, day=14), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    assert sync_issues(gh, "stocks", fine) == ["closed #1"]
    assert gh.issues[1]["state"] == "closed" and ("comment", 1) in gh.log


def test_floors_keep_their_issues_apart():
    gh = FakeGitHub()
    behind = report(status(1000.0, 110.0), QUIET, {"price": 100.0}, 1000.0, POLICY, now=NOW)
    sync_issues(gh, "stocks", behind)
    sync_issues(gh, "crypto", report(status(1000.0, 100.0), QUIET, {"price": 100.0}, 1000.0,
                                     POLICY, now=NOW))
    assert gh.issues[1]["state"] == "open"                     # crypto's quiet day closes nothing


def test_the_live_colony_files_the_note_on_the_desk_feed_every_closed_day(tmp_path):
    from cryptoarena.arena.live_colony import LiveColony
    from cryptoarena.arena.survival import SurvivalConfig
    from cryptoarena.cli import build_agents
    from cryptoarena.learning.memory import TradeJournal
    from test_live_colony import HOUR, T0, FakeClient, make_feed

    client = FakeClient()
    client.now = T0 + 120 * HOUR                     # midnight: the first bar closes day 1
    journal = TradeJournal(tmp_path / "live.db")
    colony = LiveColony.open(journal, build_agents(5.0, False, ""),
                             SurvivalConfig(budget=5.0, seed=1, endogenous=False, daily_cost=0.0),
                             make_feed(client), warmup=100, verbose=False,
                             chief=ChiefPolicy(benchmark="BTCUSD", stale_days=99))
    notes = journal._conn.execute(
        "SELECT day, detail FROM survival_events WHERE event = 'chief_note'").fetchall()
    assert [d for d, _ in notes] == [1] and "BTCUSD" in notes[0][1]
    st = colony.status()
    assert st["chief"]["benchmark"] == "BTCUSD" and st["chief"]["bench_start"]["price"] > 0
    journal.close()
