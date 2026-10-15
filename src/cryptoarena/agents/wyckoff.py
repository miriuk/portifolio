"""Richard Wyckoff's method, read mechanically from price and volume.

Wyckoff (1873-1934) read the tape as the footprint of a "composite
operator", the large money that cannot buy or sell at once. Before a rise
it *accumulates* inside a trading range after a fall; before a fall it
*distributes* inside a range after a rise. Each campaign leaves events:

- accumulation: the **spring** (price slips under the range's support and
  closes back inside: supply exhausted), the **sign of strength** (SOS: a
  close above the range's resistance on heavy volume) and the **last
  point of support** (LPS: a quiet pullback that holds above the old
  resistance);
- distribution: the **upthrust** (UTAD: a push above resistance that
  closes back inside on heavy volume) and the **sign of weakness** (SOW: a
  close under support on heavy volume).

`read()` finds the range in the bars before the most recent ones, its
context (the trend that led into it), and the latest event among the
recent bars, scored from +1 (accumulation done, markup starting) to -1
(distribution done, markdown starting). The rules are the textbook ones
made explicit; whether they predict anything is for the backtest to say.
"""
from __future__ import annotations

from dataclasses import dataclass

BULL_EVENTS = {"spring": 0.7, "sos": 0.8, "lps": 0.5}
BEAR_EVENTS = {"upthrust": -0.7, "sow": -0.8}
HEAVY = 1.5          # heavy volume: this many times the range's average
_CACHE: dict[tuple, "WyckoffRead"] = {}


@dataclass(frozen=True)
class WyckoffRead:
    phase: str            # accumulation | distribution | markup | markdown | none
    event: str            # spring | sos | lps | upthrust | sow | ""
    score: float          # -1 .. +1
    support: float = 0.0
    resistance: float = 0.0

    @property
    def bullish(self) -> bool:
        return self.score > 0

    @property
    def bearish(self) -> bool:
        return self.score < 0


NONE = WyckoffRead("none", "", 0.0)


def read(candles, range_bars: int = 40, max_width: float = 0.25) -> WyckoffRead:
    """The Wyckoff read of a series of candles (oldest first): the trading
    range is the `range_bars` bars before the latest `range_bars // 8`, its
    context the `range_bars` before that. A range wider than `max_width`
    of its midpoint is a trend, not a range: no read."""
    k = max(2, range_bars // 8)
    if range_bars < 8 or len(candles) < 2 * range_bars + k:
        return NONE
    rng = candles[-(range_bars + k):-k]
    recent = candles[-k:]
    prior = candles[-(2 * range_bars + k)]
    support = min(c.low for c in rng)
    resistance = max(c.high for c in rng)
    mid = (support + resistance) / 2
    if mid <= 0 or (resistance - support) / mid > max_width:
        return NONE
    avg_vol = sum(c.volume for c in rng) / len(rng)
    heavy = avg_vol * HEAVY if avg_vol > 0 else float("inf")
    after_fall = rng[0].close < prior.close
    last = candles[-1]

    event = ""
    for i, c in enumerate(recent):                      # the latest event wins
        if c.close < support and c.volume >= heavy:
            event = "sow"
        elif c.close > resistance and c.volume >= heavy:
            event = "sos"
        elif c.low < support <= c.close:
            event = "spring"
        elif c.high > resistance >= c.close and c.volume >= avg_vol * 1.2:
            event = "upthrust"
        elif event == "sos" and c.low >= resistance * 0.98 and c.volume < avg_vol:
            event = "lps"                               # a quiet pullback that holds
    # an event the latest close has already undone does not stand
    if event in ("spring", "lps", "sos") and last.close < support:
        event = ""
    if event in ("upthrust", "sow") and last.close > resistance:
        event = ""
    if event == "spring" and not after_fall and last.close < mid:
        event = ""                                      # a spring belongs to accumulation

    if last.close > resistance:
        phase = "markup"
    elif last.close < support:
        phase = "markdown"
    else:
        phase = "accumulation" if after_fall else "distribution"
    score = BULL_EVENTS.get(event, 0.0) + BEAR_EVENTS.get(event, 0.0)
    return WyckoffRead(phase, event, score, support, resistance)


def cached_read(symbol: str, history, range_bars: int, max_width: float = 0.25) -> WyckoffRead:
    """`read` once per symbol, bar and setting, shared by every agent that
    looks (they all see the same tape)."""
    if not history:
        return NONE
    last = history[-1]
    key = (symbol, last.timestamp, last.close, len(history), range_bars, max_width)
    hit = _CACHE.get(key)
    if hit is None:
        if len(_CACHE) > 20_000:
            _CACHE.clear()
        need = 2 * range_bars + max(2, range_bars // 8)
        hit = _CACHE[key] = read(list(history)[-need:], range_bars, max_width)
    return hit
