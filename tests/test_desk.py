"""The desk above the agents: a risk officer who sees the whole colony, and
a PM whose single book is built from the agents' votes."""
from cryptoarena.agents.base import TradingAgent
from cryptoarena.arena.desk import Desk, DeskLimits, PMBook
from cryptoarena.arena.episode import run_episode
from cryptoarena.arena.live_colony import LiveColony
from cryptoarena.arena.survival import SurvivalConfig, run_survival
from cryptoarena.cli import build_agents
from cryptoarena.learning.memory import TradeJournal
from cryptoarena.market.candle import Candle
from cryptoarena.market.exchange import Order, SimulatedExchange

from test_live_colony import HOUR, T0, FakeClient, make_feed


class Buyer(TradingAgent):
    """Buys `amount` of `symbol` on its first bar, then sits."""

    def __init__(self, agent_id, cash, symbol="AAA", amount=30.0):
        super().__init__(agent_id, cash)
        self.symbol, self.amount, self.done = symbol, amount, False

    def decide(self, view):
        if self.done:
            return []
        self.done = True
        return [Order(self.agent_id, self.symbol, "buy", self.amount, "test")]


class Tape:
    def __init__(self, prices):
        self.prices = prices
        self._regime = {}

    def next_candles(self):
        return [Candle(s, 0, p, p, p, p, 1e9) for s, p in self.prices.items()]


def _events(journal, event):
    return journal._conn.execute(
        "SELECT agent_id, detail FROM survival_events WHERE event = ? ORDER BY id",
        (event,)).fetchall()


def test_the_risk_officer_caps_one_symbol_across_all_agents(tmp_path):
    """Five agents buying the same name each stay inside their own limits
    (25% of their equity); together they would be 25% of the colony. The
    desk lets the colony reach its 20% cap and refuses the rest, in writing."""
    journal = TradeJournal(tmp_path / "d.db")
    agents = [Buyer(f"a-{i}", 100.0, amount=25.0) for i in range(5)]
    desk = Desk(limits=DeskLimits(symbol_cap=0.20), journal=journal, day=1)
    run_episode(1, Tape({"AAA": 10.0, "BBB": 5.0}), agents, journal, steps=1,
                exchange=SimulatedExchange(fee_rate=0.0, slippage_base=0.0, seed=1), desk=desk)
    held = sum(a.wallet.positions.get("AAA", 0.0) * 10.0 for a in agents)
    assert held <= 0.20 * 500 + 1e-6
    assert held >= 0.20 * 500 - 1.0                        # the room was used, not wasted
    assert desk.vetoes >= 1
    notes = _events(journal, "vetoed") + _events(journal, "clipped")
    assert notes and all("AAA" in d and "cap 20%" in d for _, d in notes)
    journal.close()


def test_closing_a_position_is_never_refused(tmp_path):
    journal = TradeJournal(tmp_path / "d.db")
    desk = Desk(limits=DeskLimits(symbol_cap=0.01, gross_cap=0.01), journal=journal)
    agent = Buyer("a-1", 100.0)
    agent.wallet.positions["AAA"] = 5.0
    sell = Order("a-1", "AAA", "sell", 5.0, "exit")
    assert desk.vet(sell, agent, [agent], {"AAA": 10.0}) is sell
    journal.close()


def test_turns_rotate_so_the_room_under_a_cap_is_shared(tmp_path):
    journal = TradeJournal(tmp_path / "d.db")
    exchange = SimulatedExchange(fee_rate=0.0, slippage_base=0.0, seed=1)
    firsts = []
    for offset in range(3):
        agents = [Buyer(f"a-{i}", 100.0, amount=60.0) for i in range(3)]
        desk = Desk(limits=DeskLimits(symbol_cap=0.10), journal=journal)
        run_episode(1, Tape({"AAA": 10.0}), agents, journal, steps=1, exchange=exchange,
                    desk=desk, step_offset=offset)
        firsts.append(max(agents, key=lambda a: a.wallet.positions.get("AAA", 0.0)).agent_id)
    assert len(set(firsts)) == 3
    journal.close()


def test_the_pm_holds_the_colonys_net_book_and_nets_opposite_trades():
    """Two agents hold opposite halves of the same idea: the PM's book is
    their equity-weighted weights, and a swap between them moves nothing."""
    a, b = Buyer("a", 100.0), Buyer("b", 100.0)
    a.wallet.cash, a.wallet.positions = 50.0, {"AAA": 5.0}           # 50% in AAA
    b.wallet.cash, b.wallet.positions = 100.0, {}
    prices = {"AAA": 10.0}
    book = PMBook(200.0, band=0.02)
    assert book.votes([a, b], prices) == {"AAA": 0.25}
    latest = {"AAA": Candle("AAA", 0, 10, 10, 10, 10, 1e9)}
    ex = SimulatedExchange(fee_rate=0.0, slippage_base=0.0, seed=1)
    book.rebalance([a, b], latest, prices, ex)
    assert abs(book.wallet.positions["AAA"] * 10 / book.wallet.equity(prices) - 0.25) < 0.01
    a.wallet.positions, a.wallet.cash = {}, 100.0                   # a sells to b
    b.wallet.positions, b.wallet.cash = {"AAA": 5.0}, 50.0
    assert book.rebalance([a, b], latest, prices, ex) == []          # nothing for the PM to do


def test_consensus_drops_what_too_few_agents_hold():
    agents = [Buyer(f"a-{i}", 100.0) for i in range(4)]
    agents[0].wallet.positions = {"AAA": 5.0}
    agents[0].wallet.cash = 50.0
    for a in agents[:3]:
        a.wallet.positions.setdefault("BBB", 2.0)
    book = PMBook(400.0, consensus=0.5)
    votes = book.votes(agents, {"AAA": 10.0, "BBB": 10.0})
    assert "AAA" not in votes and votes["BBB"] > 0


def test_the_pm_book_is_a_shadow_that_leaves_the_colony_alone(tmp_path):
    """Same seed, PM on or off: the agents' results are identical, and the
    PM's book ends up somewhere sensible next to them."""
    def run(pm):
        journal = TradeJournal(tmp_path / f"s{pm}.db")
        res = run_survival(build_agents(100.0, False, ""), journal,
                           SurvivalConfig(days=4, budget=100.0, seed=3, endogenous=False, pm=pm,
                                          pm_band=0.02),
                           verbose=False)
        out = [round(i.agent.wallet.cash, 8) for i in res.population], res
        journal.close()
        return out
    (off, _), (on, res) = run(False), run(True)
    assert off == on
    book = res.desk.pm
    assert len(book.equity_per_day) == 4
    assert 0.5 * book.capital < book.equity_per_day[-1] < 1.5 * book.capital


def test_a_running_colony_staffs_the_desk_from_the_floor_policy(tmp_path):
    """The desk is policy, like the founders: a tick with the PM switched on
    opens its book in the running colony, the book survives restarts, and
    a status read (no founders) changes nothing."""
    client = FakeClient()
    client.now = T0 + 120 * HOUR
    db = tmp_path / "live.db"
    base = dict(budget=5.0, seed=1, endogenous=False, daily_cost=0.0)
    journal = TradeJournal(db)
    LiveColony.open(journal, build_agents(5.0, False, ""), SurvivalConfig(**base),
                    make_feed(client), warmup=100, verbose=False)
    journal.close()

    client.now += 3 * HOUR
    journal = TradeJournal(db)
    policy = SurvivalConfig(**base, desk_symbol_cap=0.2, pm=True, pm_band=0.02)
    colony = LiveColony.open(journal, build_agents(5.0, False, ""), policy, make_feed(client),
                             warmup=100, verbose=False)
    assert colony.desk is not None and colony.desk.pm is not None
    opened_on = colony.pm_start["day"]
    colony.run_once()
    fills = len(colony.desk.pm.fills)
    status = colony.status()["desk"]
    assert status["symbol_cap"] == 0.2 and status["pm"]["since_day"] == opened_on
    journal.close()

    journal = TradeJournal(db)
    from cryptoarena.cli import _StaticFeed
    reread = LiveColony.open(journal, [], SurvivalConfig(), _StaticFeed("1h", "kraken", []),
                             verbose=False)
    assert reread.desk.pm is not None and len(reread.desk.pm.fills) == fills
    assert reread.pm_start["day"] == opened_on
    assert len(_events(journal, "pm_opened")) == 1
    journal.close()
