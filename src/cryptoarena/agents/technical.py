"""The technical-analysis course: twenty-one techniques traders swear by,
each made mechanical so it can be tested instead of believed.

Every detector takes one symbol's daily bars (a DataFrame with open,
high, low, close, volume, timestamp; oldest first) and returns a Series
on the same rows: +1 (a buy setup completes on this bar's close), -1 (a
sell setup) or 0. Only what was known at that close is used: swing
points (pivots) count from the bar that *confirms* them, `k` bars after
the extreme, never from the extreme itself. `arena/lookahead.py` checks
every detector by scrambling the future.

Many of these techniques are drawn by hand and argued about; the rules
here are the textbook versions made explicit, one reasonable reading
each, with their parameters fixed before looking at any result.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- helpers


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def raw_pivots(df: pd.DataFrame, k: int = 5) -> list[tuple]:
    """Swing highs and lows: a bar whose high (low) is the highest (lowest)
    of the k bars on each side, as (i, seen, price, kind): the extreme's
    row, the row it becomes known (i + k), its price, +1 high / -1 low."""
    h, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    rows = []
    for i in range(k, len(df) - k):
        win_h, win_l = h[i - k:i + k + 1], lo[i - k:i + k + 1]
        if h[i] == win_h.max() and (win_h == h[i]).sum() == 1:
            rows.append((i, i + k, float(h[i]), 1))
        if lo[i] == win_l.min() and (win_l == lo[i]).sum() == 1:
            rows.append((i, i + k, float(lo[i]), -1))
    return sorted(rows, key=lambda r: (r[1], r[0]))


def pivot_states(df: pd.DataFrame, k: int = 5, keep: int = 8) -> list[list[tuple]]:
    """For every row t, the alternating swing points an observer knew at
    t's close (the last `keep`), built one confirmation at a time: a new
    swing of the same kind as the last replaces it only if more extreme,
    from the row it is seen on. Nothing later reaches back to remove a
    point that was already known."""
    raw = raw_pivots(df, k)
    states, cur, j = [], [], 0
    for t in range(len(df)):
        changed = False
        while j < len(raw) and raw[j][1] <= t:
            r = raw[j]
            j += 1
            if cur and cur[-1][3] == r[3]:
                if (r[3] == 1 and r[2] > cur[-1][2]) or (r[3] == -1 and r[2] < cur[-1][2]):
                    cur = cur[:-1] + [r]
                    changed = True
                continue
            cur = (cur + [r])[-keep:]
            changed = True
        states.append(cur if changed or not states else states[-1])
    return states


def _first(sig: pd.Series, gap: int = 5) -> pd.Series:
    """Keep a signal only where the same side did not fire in the last `gap` bars."""
    out = sig.copy()
    v = sig.to_numpy()
    last = {1: -10**9, -1: -10**9}
    res = np.zeros(len(v), dtype=int)
    for i, s in enumerate(v):
        if s and i - last[int(s)] > gap:
            res[i] = int(s)
        if s:
            last[int(s)] = i
    out[:] = res
    return out


def _from_events(n: int, index, events: dict[int, int]) -> pd.Series:
    s = np.zeros(n, dtype=int)
    for t, v in events.items():
        if 0 <= t < n:
            s[t] = v
    return pd.Series(s, index=index)


# ---------------------------------------------------------------- the course


def fibonacci(df, k=5, lo_ratio=0.5, hi_ratio=0.618, floor=0.786):
    """After a confirmed swing low → high leg, a pullback into the 50–61.8%
    retracement that closes up and above 78.6% is a buy; the mirror after
    a high → low leg is a sell."""
    states = pivot_states(df, k)
    o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ev = {}
    for t, known in enumerate(states):
        if len(known) < 2:
            continue
        a, b = known[-2], known[-1]
        leg = b[2] - a[2]
        if a[3] == -1 and b[3] == 1 and leg > 0:                    # up leg
            zone_hi, zone_lo = b[2] - lo_ratio * leg, b[2] - hi_ratio * leg
            if lo[t] <= zone_hi and lo[t] >= b[2] - floor * leg and c[t] > o[t] and c[t] > zone_lo:
                ev[t] = 1
        elif a[3] == 1 and b[3] == -1 and leg < 0:                  # down leg
            leg = -leg
            zone_lo, zone_hi = b[2] + lo_ratio * leg, b[2] + hi_ratio * leg
            if h[t] >= zone_lo and h[t] <= b[2] + floor * leg and c[t] < o[t] and c[t] < zone_hi:
                ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def breakout(df, n=20, vol_mult=1.5):
    """A close beyond the last n bars' high (low) on volume above
    vol_mult × its n-bar average."""
    hi = df["high"].shift(1).rolling(n).max()
    lo = df["low"].shift(1).rolling(n).min()
    heavy = df["volume"] > vol_mult * df["volume"].shift(1).rolling(n).mean()
    sig = (df["close"] > hi) & heavy
    sig = sig.astype(int) - ((df["close"] < lo) & heavy).astype(int)
    return _first(sig)


def reversal_patterns(df, k=5, tol=0.03):
    """Double bottom / top and (inverse) head and shoulders, entered when
    the close breaks the neckline."""
    states = pivot_states(df, k)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        known = states[t]
        if len(known) < 5:
            continue
        kinds = [p[3] for p in known[-5:]]
        px = [p[2] for p in known[-5:]]
        if kinds[-3:] == [-1, 1, -1] and abs(px[-1] / px[-3] - 1) < tol and c[t] > px[-2] >= c[t - 1]:
            ev[t] = 1                                              # double bottom
        elif kinds[-3:] == [1, -1, 1] and abs(px[-1] / px[-3] - 1) < tol and c[t] < px[-2] <= c[t - 1]:
            ev[t] = -1                                             # double top
        elif kinds == [1, -1, 1, -1, 1] and px[2] > max(px[0], px[4]) \
                and abs(px[4] / px[0] - 1) < 2 * tol and c[t] < min(px[1], px[3]) <= c[t - 1]:
            ev[t] = -1                                             # head and shoulders
        elif kinds == [-1, 1, -1, 1, -1] and px[2] < min(px[0], px[4]) \
                and abs(px[4] / px[0] - 1) < 2 * tol and c[t] > max(px[1], px[3]) >= c[t - 1]:
            ev[t] = 1                                              # inverse
    return _first(_from_events(len(df), df.index, ev))


def elliott(df, k=5):
    """The classic Elliott entry: waves 1 and 2 are in (a swing up, then a
    pullback of 50–78.6% that holds above the start), and the close breaks
    the top of wave 1 — wave 3, the longest, should be starting. Mirror for
    a down impulse."""
    states = pivot_states(df, k)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        known = states[t]
        if len(known) < 3:
            continue
        p0, p1, p2 = known[-3:]
        if (p0[3], p1[3], p2[3]) == (-1, 1, -1):
            w1 = p1[2] - p0[2]
            retr = (p1[2] - p2[2]) / w1 if w1 > 0 else 0
            if 0.5 <= retr <= 0.786 and c[t] > p1[2] >= c[t - 1]:
                ev[t] = 1
        elif (p0[3], p1[3], p2[3]) == (1, -1, 1):
            w1 = p0[2] - p1[2]
            retr = (p2[2] - p1[2]) / w1 if w1 > 0 else 0
            if 0.5 <= retr <= 0.786 and c[t] < p1[2] <= c[t - 1]:
                ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def fair_value_gap(df, life=20):
    """A three-bar gap (bar j's low above bar j-2's high: buyers left a
    hole). The first return into the gap that closes above it is a buy;
    the mirror is a sell."""
    h, lo, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    n = len(df)
    ev = {}
    open_gaps: list[tuple[int, float, float, int]] = []      # (born, bottom, top, side)
    for t in range(n):
        keep = []
        for born, bottom, top, side in open_gaps:
            if t - born > life:
                continue
            if side == 1 and lo[t] <= top and c[t] > bottom:
                ev[t] = 1
                continue
            if side == -1 and h[t] >= bottom and c[t] < top:
                ev[t] = -1
                continue
            keep.append((born, bottom, top, side))
        open_gaps = keep
        if t >= 2 and lo[t] > h[t - 2]:
            open_gaps.append((t, h[t - 2], lo[t], 1))
        if t >= 2 and h[t] < lo[t - 2]:
            open_gaps.append((t, h[t], lo[t - 2], -1))
    return _first(_from_events(n, df.index, ev))


def candlesticks(df):
    """Engulfing, hammer / shooting star (after a 5-bar move), and the
    morning / evening star."""
    o, h, lo, c = (df[x] for x in ("open", "high", "low", "close"))
    body = (c - o).abs()
    rng = (h - lo).replace(0, np.nan)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - lo
    down5 = c.shift(1) < c.shift(6)
    up5 = c.shift(1) > c.shift(6)
    bull_engulf = (c.shift(1) < o.shift(1)) & (c > o) & (c >= o.shift(1)) & (o <= c.shift(1))
    bear_engulf = (c.shift(1) > o.shift(1)) & (c < o) & (c <= o.shift(1)) & (o >= c.shift(1))
    hammer = down5 & (lower >= 2 * body) & (upper <= 0.3 * body + 0.1 * rng)
    star = up5 & (upper >= 2 * body) & (lower <= 0.3 * body + 0.1 * rng)
    small = body.shift(1) < 0.3 * rng.shift(1)
    morning = (c.shift(2) < o.shift(2)) & small & (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)
    evening = (c.shift(2) > o.shift(2)) & small & (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)
    sig = (bull_engulf & down5 | hammer | morning).astype(int) - \
        (bear_engulf & up5 | star | evening).astype(int)
    return _first(sig.clip(-1, 1))


def heikin_ashi(df):
    """Heikin-Ashi candles: a green candle with no lower shadow after red
    ones is a buy; a red one with no upper shadow after green, a sell."""
    o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    ha_c = (o + h + lo + c) / 4
    ha_o = np.empty(n)
    ha_o[0] = (o[0] + c[0]) / 2
    for i in range(1, n):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    ha_h = np.maximum.reduce([h, ha_o, ha_c])
    ha_l = np.minimum.reduce([lo, ha_o, ha_c])
    green = ha_c > ha_o
    sig = np.zeros(n, dtype=int)
    for i in range(1, n):
        if green[i] and not green[i - 1] and ha_l[i] >= min(ha_o[i], ha_c[i]) - 1e-12:
            sig[i] = 1
        elif not green[i] and green[i - 1] and ha_h[i] <= max(ha_o[i], ha_c[i]) + 1e-12:
            sig[i] = -1
    return _first(pd.Series(sig, index=df.index))


NEW_MOON = 947182440            # 2000-01-06 18:14 UTC
SYNODIC = 29.530588853 * 86400


def moon_phase(ts) -> np.ndarray:
    """0 at new moon, 0.5 at full moon."""
    return ((np.asarray(ts, float) - NEW_MOON) / SYNODIC) % 1.0


def moon(df, window_days=3):
    """Yuan, Zheng & Zhu (2006) found stock returns lower around full moons
    than around new moons. The bar that enters the new-moon window is a
    buy, the one entering the full-moon window a sell."""
    ph = moon_phase(df["timestamp"].to_numpy())
    w = window_days / 29.530588853
    new = (ph < w) | (ph > 1 - w)
    full = np.abs(ph - 0.5) < w
    s = pd.Series(new.astype(int) - full.astype(int), index=df.index)
    return _first(s.where(s != s.shift(1), 0), gap=10)


def renko(df, n=14):
    """Renko bricks one ATR tall: a brick up after down bricks is a buy,
    a brick down after up bricks a sell."""
    c = df["close"].to_numpy(float)
    box = atr(df, n).to_numpy(float)
    sig = np.zeros(len(c), dtype=int)
    ref, last_dir = None, 0
    for i in range(len(c)):
        b = box[i]
        if not b == b or b <= 0:
            continue
        if ref is None:
            ref = c[i]
            continue
        moved = 0
        while c[i] >= ref + b:
            ref += b
            moved = 1
        while c[i] <= ref - b:
            ref -= b
            moved = -1
        if moved and moved != last_dir:
            if last_dir:
                sig[i] = moved
            last_dir = moved
    return _first(pd.Series(sig, index=df.index))


HARMONICS = {   # name: (B as a share of XA, D as a share of XA), ±tolerance
    "gartley": (0.618, 0.786), "bat": (0.45, 0.886), "butterfly": (0.786, 1.27), "crab": (0.5, 1.618),
}


def harmonic(df, k=5, tol=0.08):
    """XABCD from the last five swing points, matched to Gartley, Bat,
    Butterfly or Crab by the B and D retracements of XA (BC 38.2–88.6% of
    AB). A bullish pattern completes at a swing low D, on the bar D is
    confirmed (buy); bearish at a swing high (sell)."""
    states = pivot_states(df, k)
    ev = {}
    for t, known in enumerate(states):
        if len(known) < 5 or known[-1][1] != t:
            continue                                   # only when D has just been confirmed
        x, a, b, cc, d = (p[2] for p in known[-5:])
        xa = a - x
        ab = b - a
        if xa == 0 or ab == 0:
            continue
        b_ret, d_ret, bc_ret = -ab / xa, (a - d) / xa, -(cc - b) / ab
        if not 0.382 - tol <= bc_ret <= 0.886 + tol:
            continue
        for b_t, d_t in HARMONICS.values():
            if abs(b_ret - b_t) <= tol and abs(d_ret - d_t) <= tol * max(1, d_t):
                ev[t] = 1 if known[-1][3] == -1 else -1
                break
    return _first(_from_events(len(df), df.index, ev))


def support_resistance(df, k=5, lookback=120, tol=0.01):
    """Horizontal levels from the swing points of the last `lookback` bars.
    A bar that dips to within tol of a support and closes up above it is a
    buy; one that tags a resistance and closes down below it, a sell."""
    raw = raw_pivots(df, k)
    o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ev = {}
    for t in range(len(df)):
        lv = [(p, kind) for i, seen, p, kind in raw if seen <= t and i >= t - lookback]
        sup = np.array([p for p, kind in lv if kind == -1 and p < c[t]])
        res = np.array([p for p, kind in lv if kind == 1 and p > c[t]])
        if len(sup) and c[t] > o[t] and (np.abs(lo[t] / sup - 1) <= tol).any():
            ev[t] = 1
        elif len(res) and c[t] < o[t] and (np.abs(h[t] / res - 1) <= tol).any():
            ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def dynamic_support(df, fast=20, slow=50):
    """In an uptrend (close over a rising 50-bar EMA) a dip that touches the
    20-bar EMA and closes above it is a buy; the mirror is a sell."""
    e_f = df["close"].ewm(span=fast, adjust=False).mean()
    e_s = df["close"].ewm(span=slow, adjust=False).mean()
    up = (df["close"] > e_s) & (e_s > e_s.shift(5))
    down = (df["close"] < e_s) & (e_s < e_s.shift(5))
    buy = up & (df["low"] <= e_f) & (df["close"] > e_f)
    sell = down & (df["high"] >= e_f) & (df["close"] < e_f)
    return _first(buy.astype(int) - sell.astype(int))


def trend_lines(df, k=5):
    """The line through the last two swing highs, if falling: a close
    across it is a buy. Through the last two swing lows, if rising: a
    close under it is a sell."""
    states = pivot_states(df, k)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        known = states[t]
        highs = [p for p in known if p[3] == 1][-2:]
        lows = [p for p in known if p[3] == -1][-2:]
        if len(highs) == 2 and highs[1][2] < highs[0][2]:
            (i1, _, p1, _), (i2, _, p2, _) = highs
            slope = (p2 - p1) / (i2 - i1)
            if c[t] > p2 + slope * (t - i2) and c[t - 1] <= p2 + slope * (t - 1 - i2):
                ev[t] = 1
        if t not in ev and len(lows) == 2 and lows[1][2] > lows[0][2]:
            (i1, _, p1, _), (i2, _, p2, _) = lows
            slope = (p2 - p1) / (i2 - i1)
            if c[t] < p2 + slope * (t - i2) and c[t - 1] >= p2 + slope * (t - 1 - i2):
                ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def gann_fan(df, k=10, n=60):
    """Gann's 1×1 line from the last major swing point: one unit of price
    per bar, the unit being the average absolute daily move of the last n
    bars at the pivot (Gann's "balance" of price and time). Rising from a
    swing low, falling from a swing high: a close back above it is a buy,
    a close below it a sell."""
    states = pivot_states(df, k)
    a = df["close"].diff().abs().rolling(n).mean().to_numpy(float)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        if not states[t]:
            continue
        i, _, price, kind = states[t][-1]
        unit = a[i]
        if not unit == unit or unit <= 0:
            continue
        sign = 1 if kind == -1 else -1
        line, prev = price + sign * unit * (t - i), price + sign * unit * (t - 1 - i)
        if c[t] > line and c[t - 1] <= prev:
            ev[t] = 1
        elif c[t] < line and c[t - 1] >= prev:
            ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def oscillators(df, n=14, low=30, high=70):
    """RSI back up through 30 is a buy, back down through 70 a sell."""
    r = rsi(df["close"], n)
    buy = (r > low) & (r.shift(1) <= low)
    sell = (r < high) & (r.shift(1) >= high)
    return _first(buy.astype(int) - sell.astype(int))


def divergence(df, k=5, n=14):
    """Price makes a lower swing low while RSI makes a higher one (bullish
    divergence, buy on the bar the second low is confirmed); the mirror at
    swing highs is a sell."""
    states = pivot_states(df, k)
    r = rsi(df["close"], n).to_numpy(float)
    ev = {}
    for t, known in enumerate(states):
        if len(known) < 3 or known[-1][1] != t:
            continue
        a, b = known[-3], known[-1]                    # the same kind, one swing apart
        ra, rb = r[a[0]], r[b[0]]
        if not (ra == ra and rb == rb):
            continue
        if b[3] == -1 and b[2] < a[2] and rb > ra:
            ev[t] = 1
        elif b[3] == 1 and b[2] > a[2] and rb < ra:
            ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def volume_flow(df, n=20):
    """On-balance volume crossing its n-bar average on an up close is a buy,
    crossing down on a down close a sell."""
    step = np.sign(df["close"].diff()).fillna(0)
    obv = (step * df["volume"]).cumsum()
    avg = obv.rolling(n).mean()
    buy = (obv > avg) & (obv.shift(1) <= avg.shift(1)) & (step > 0)
    sell = (obv < avg) & (obv.shift(1) >= avg.shift(1)) & (step < 0)
    return _first(buy.astype(int) - sell.astype(int))


def supply_demand(df, n=14, impulse=2.0, life=60):
    """A demand zone is the quiet base bar right before a move of
    `impulse` ATRs in at most three bars; the first return into it is a
    buy. Supply zones, mirrored, are sells."""
    o, h, lo, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    a = atr(df, n).to_numpy(float)
    zones: list[tuple[int, float, float, int]] = []          # (made, bottom, top, side)
    ev = {}
    for t in range(4, len(df)):
        keep = []
        for made, bottom, top, side in zones:
            if t - made > life:
                continue
            if side == 1 and lo[t] <= top and c[t] >= bottom:
                ev[t] = 1
                continue
            if side == -1 and h[t] >= bottom and c[t] <= top:
                ev[t] = -1
                continue
            keep.append((made, bottom, top, side))
        zones = keep
        base = t - 3
        unit = a[base]
        if not unit == unit or unit <= 0 or (h[base] - lo[base]) > unit:
            continue
        if c[t] - h[base] >= impulse * unit:
            zones.append((t, lo[base], h[base], 1))
        elif lo[base] - c[t] >= impulse * unit:
            zones.append((t, lo[base], h[base], -1))
    return _first(_from_events(len(df), df.index, ev))


def _structure(known: list[tuple]) -> tuple[int, tuple | None, tuple | None]:
    """+1 higher highs and higher lows, -1 lower highs and lower lows, 0
    neither; and the last swing high and low."""
    highs = [p for p in known if p[3] == 1][-2:]
    lows = [p for p in known if p[3] == -1][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return 0, None, None
    hh, hl = highs[1][2] > highs[0][2], lows[1][2] > lows[0][2]
    state = 1 if hh and hl else -1 if not hh and not hl else 0
    return state, highs[1], lows[1]


def market_structure(df, k=5):
    """The bar on which the swing structure turns: higher highs and lows
    confirmed (buy), lower highs and lows confirmed (sell)."""
    ev, prev = {}, 0
    for t, known in enumerate(pivot_states(df, k)):
        state, _, _ = _structure(known)
        if state and state != prev:
            ev[t] = state
        if state:
            prev = state
    return _first(_from_events(len(df), df.index, ev))


def bos(df, k=5):
    """Break of structure: in an uptrend, a close above the last swing high
    (continuation, buy); in a downtrend, below the last swing low (sell)."""
    states = pivot_states(df, k)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        state, hi, lo = _structure(states[t])
        if state == 1 and c[t] > hi[2] >= c[t - 1]:
            ev[t] = 1
        elif state == -1 and c[t] < lo[2] <= c[t - 1]:
            ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


def choch(df, k=5):
    """Change of character: in a downtrend, a close above the last lower
    high (the trend may be turning: buy); in an uptrend, a close below the
    last higher low (sell)."""
    states = pivot_states(df, k)
    c = df["close"].to_numpy(float)
    ev = {}
    for t in range(1, len(df)):
        state, hi, lo = _structure(states[t])
        if state == -1 and c[t] > hi[2] >= c[t - 1]:
            ev[t] = 1
        elif state == 1 and c[t] < lo[2] <= c[t - 1]:
            ev[t] = -1
    return _first(_from_events(len(df), df.index, ev))


# name: (detector, what it is, in Portuguese for the report)
TECHNIQUES = {
    "fibonacci": (fibonacci, "retração de Fibonacci 50–61,8%"),
    "breakout": (breakout, "rompimento de 20 barras com volume"),
    "reversal": (reversal_patterns, "fundo/topo duplo e ombro-cabeça-ombro"),
    "elliott": (elliott, "ondas de Elliott: entrada na onda 3"),
    "fvg": (fair_value_gap, "fair value gap (volta ao vazio de 3 barras)"),
    "candles": (candlesticks, "candles: engolfo, martelo, estrelas"),
    "heikin_ashi": (heikin_ashi, "Heikin-Ashi: virada sem sombra"),
    "moon": (moon, "fases da lua: lua nova compra, cheia vende"),
    "renko": (renko, "Renko de 1 ATR: tijolo virou"),
    "harmonic": (harmonic, "harmônicos: Gartley, Bat, Butterfly, Crab"),
    "sr": (support_resistance, "suporte e resistência horizontais"),
    "dynamic": (dynamic_support, "suporte dinâmico: toque na média de 20"),
    "trendline": (trend_lines, "linhas de tendência rompidas"),
    "gann": (gann_fan, "leque de Gann: linha 1×1"),
    "rsi": (oscillators, "osciladores: IFR saindo de 30/70"),
    "divergence": (divergence, "divergência preço × IFR"),
    "volume": (volume_flow, "volume: OBV cruzando a média"),
    "supply_demand": (supply_demand, "zonas de oferta e demanda"),
    "structure": (market_structure, "estrutura de mercado (topos e fundos)"),
    "bos": (bos, "BOS: rompimento de estrutura"),
    "choch": (choch, "CHoCH: mudança de caráter"),
}


def all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Every technique's signal for one symbol (rows like df)."""
    return pd.DataFrame({name: fn(df) for name, (fn, _) in TECHNIQUES.items()}, index=df.index)


def to_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """UTC days from hourly candles (open first, high max, low min, close
    last, volume sum), stamped at the day's start."""
    df = hourly.dropna(subset=["close"]).copy()
    df["day"] = (df["timestamp"] // 86400) * 86400
    g = df.groupby("day")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(),
                        "bars": g.size()})
    out = out[out["bars"] >= 20].drop(columns="bars")             # skip half days at the ends
    return out.reset_index().rename(columns={"day": "timestamp"})


# ---------------------------------------------------------------- the council

CONFIDENCE_FILE = Path(__file__).with_name("ta_confidence.json")


@lru_cache(maxsize=1)
def load_confidence(path: str | None = None) -> dict[str, float]:
    """Each technique's confidence, as the exam (learning/ta_exam.py)
    earned it: 0 for every technique whose edge did not survive."""
    f = Path(path) if path else CONFIDENCE_FILE
    if not f.exists():
        return {}
    doc = json.loads(f.read_text(encoding="utf-8"))
    return {k: float(v.get("confidence", 0.0)) for k, v in doc.get("techniques", {}).items()}


def council(df: pd.DataFrame, confidence: dict[str, float] | None = None) -> float:
    """The techniques' vote on the latest bar, each weighted by the
    confidence it earned: +1 all trusted voices say buy, -1 sell, 0 when
    they disagree, are silent, or nobody has earned a voice."""
    conf = confidence if confidence is not None else load_confidence()
    voters = {k: w for k, w in conf.items() if w > 0 and k in TECHNIQUES}
    if not voters or len(df) < 60:
        return 0.0
    total = sum(voters.values())
    return sum(w * int(TECHNIQUES[k][0](df).iloc[-1]) for k, w in voters.items()) / total


def candles_frame(history) -> pd.DataFrame:
    """An agent's candle history as the frame the detectors read."""
    return pd.DataFrame([(c.timestamp, c.open, c.high, c.low, c.close, c.volume) for c in history],
                        columns=["timestamp", "open", "high", "low", "close", "volume"])
