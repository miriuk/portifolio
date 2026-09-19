import pytest

from cryptoarena.market.candle import Candle
from cryptoarena.market.exchange import Order
from cryptoarena.market.live import LiveExchange, LiveFeed, LiveLimits


class FakeCCXT:
    """Stands in for a ccxt exchange client."""

    def __init__(self):
        self.sandbox = False
        self.orders = []

    def set_sandbox_mode(self, on):
        self.sandbox = on

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1):
        return [[1_700_000_000_000, 100.0, 101.0, 99.0, 100.5, 1234.0],
                [1_700_003_600_000, 100.5, 102.0, 100.0, 101.5, 999.0]]   # still forming

    def create_market_buy_order(self, symbol, qty):
        self.orders.append(("buy", symbol, qty))
        return {"average": 100.6, "filled": qty}

    def create_market_sell_order(self, symbol, qty):
        self.orders.append(("sell", symbol, qty))
        return {"average": 100.4, "filled": qty}


def candle(price=100.0):
    return Candle("BTCUSDT", 1_700_000_000, price, price, price, price, 1000.0)


def test_feed_maps_ccxt_ohlcv_and_skips_the_forming_candle():
    feed = LiveFeed(symbols={"BTCUSDT": "BTC/USDT"}, client=FakeCCXT(),
                    now=lambda: 1_700_003_600 + 1800)      # half-way through the second bar
    c = feed.next_candles()[0]
    assert c.symbol == "BTCUSDT" and c.close == 100.5 and c.timestamp == 1_700_000_000
    raw = LiveFeed(symbols={"BTCUSDT": "BTC/USDT"}, client=FakeCCXT(), closed_only=False)
    assert raw.next_candles()[0].timestamp == 1_700_003_600


def test_dry_run_never_touches_the_exchange():
    fake = FakeCCXT()
    ex = LiveExchange(dry_run=True, client=fake)
    fill = ex.execute(Order("a", "BTCUSDT", "buy", 20.0), candle())
    assert fill is not None and fill.quantity > 0
    assert fake.orders == []  # nothing sent


def test_testnet_enabled_by_default():
    fake = FakeCCXT()
    LiveExchange(dry_run=True, client=fake)
    assert fake.sandbox is True


def test_per_order_cap_clips():
    ex = LiveExchange(dry_run=True, client=FakeCCXT(),
                      limits=LiveLimits(max_order_quote=50.0,
                                        approve_above_quote=1000.0))
    fill = ex.execute(Order("a", "BTCUSDT", "buy", 500.0), candle())
    assert fill.quantity * fill.price + fill.fee <= 50.0 + 1e-6


def test_daily_cap_stops_buys():
    ex = LiveExchange(dry_run=True, client=FakeCCXT(),
                      limits=LiveLimits(max_order_quote=100.0,
                                        max_daily_quote=100.0,
                                        approve_above_quote=1000.0))
    assert ex.execute(Order("a", "BTCUSDT", "buy", 80.0), candle()) is not None
    second = ex.execute(Order("a", "BTCUSDT", "buy", 80.0), candle())
    assert second is not None  # clipped into the remaining 20
    assert ex.execute(Order("a", "BTCUSDT", "buy", 10.0), candle()) is None
    # sells are never blocked by the daily buy cap
    assert ex.execute(Order("a", "BTCUSDT", "sell", 0.001), candle()) is not None


def test_approval_required_above_threshold():
    ex = LiveExchange(dry_run=True, client=FakeCCXT(),
                      limits=LiveLimits(approve_above_quote=25.0))
    assert ex.execute(Order("a", "BTCUSDT", "buy", 40.0), candle()) is None  # no callback
    approved = []
    ex_ok = LiveExchange(dry_run=True, client=FakeCCXT(),
                         limits=LiveLimits(approve_above_quote=25.0),
                         confirm=lambda o, v: approved.append(v) or True)
    assert ex_ok.execute(Order("a", "BTCUSDT", "buy", 40.0), candle()) is not None
    assert approved == [40.0]


def test_real_order_path_uses_client():
    fake = FakeCCXT()
    ex = LiveExchange(dry_run=False, client=fake, symbols={"BTCUSDT": "BTC/USDT"},
                      limits=LiveLimits(approve_above_quote=1000.0))
    fill = ex.execute(Order("a", "BTCUSDT", "buy", 20.0), candle())
    assert fake.orders and fake.orders[0][0] == "buy"
    assert fill.price == pytest.approx(100.6)
