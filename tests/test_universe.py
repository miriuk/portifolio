from cryptoarena.market.universe import (CORPORATE_ACTIONS, LARGE_CAPS, WORLD_ETFS,
                                         adjust_corporate_actions, asset_class)

DAY = 86400
T0 = 1782518400                      # 2026-06-27 00:00 UTC


def test_a_spin_off_leaves_no_crash_behind():
    rows = [[T0 - DAY, 460, 466, 458, 464.42, 1e6], [T0 + 2 * DAY, 230, 231, 226, 227.8, 1e6],
            [T0 + 3 * DAY, 228, 232, 227, 230.0, 1e6]]
    out = adjust_corporate_actions("HON", rows)
    assert out[1][4] / out[0][4] == 1.0                     # the spin-off day: no return
    assert out[2] == rows[2] and out[1] == rows[1]           # after it: untouched
    assert out[0][5] == rows[0][5]                           # volume is not a price
    assert adjust_corporate_actions("AAPL", rows) == rows


def test_the_universe_is_consistent():
    assert "HON" in LARGE_CAPS and set(CORPORATE_ACTIONS) <= set(LARGE_CAPS)
    assert not set(WORLD_ETFS) & set(LARGE_CAPS)
    assert asset_class("EWU") == "etf" and asset_class("AAPL") == "stocks"
