"""Sources: people the colony listens to, and the ledger that decides
how much.

A source is an account on X whose posts sometimes call a coin — "$SOL
looks ready", "shorting ETH here". The colony turns each post into
*calls* (symbol, direction, when), notes the price at that moment, and
judges the call after `horizon_days`: did the coin move the way the
source said? Every source keeps a track record in the journal, and the
weight its calls carry — its *trust* — comes from that record, not from
its follower count:

    trust = prior                      while fewer than `min_resolved` calls are judged
    trust = 2 * hit_rate - 1           afterwards, blended in as the record grows

A source that is right 70% of the time pulls the colony its way with
trust 0.4; one that is right 50% is noise (trust 0); one that is usually
wrong ends up with negative trust and the colony fades it. Agents see the
sum of the active calls per symbol as `MarketView.signals`, in [-1, 1].

Posts arrive two ways: the X API (pay-per-use, needs `X_BEARER_TOKEN`),
or by hand — `cryptoarena call --source leshka_eth --url … --text "…"` /
the workflow's "post" input — for the days nobody pays for the API.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    handle: str                       # the X handle, without the @
    label: str = ""
    prior: float = 0.25               # trust before the ledger has judged enough calls
    horizon_days: int = 7             # a call is judged this many days after the post
    min_resolved: int = 10            # judged calls before the record replaces the prior
    url: str = ""

    @property
    def link(self) -> str:
        return self.url or f"https://x.com/{self.handle}"


@dataclass
class Post:
    source: str
    post_id: str
    ts: int                           # unix seconds
    text: str
    url: str = ""


@dataclass
class Call:
    source: str
    post_id: str
    ts: int
    symbol: str                       # arena symbol, e.g. BTCUSD
    side: int                         # +1 long, -1 short
    text: str = ""
    url: str = ""
    price_at: float | None = None     # the price when the colony first saw the call
    resolved_ts: int | None = None
    outcome: float | None = None      # return in the call's direction at resolution
    id: int | None = None


# ------------------------------------------------------------------ parsing
# Names people use for the majors; tickers match as $BTC or a bare BTC.
COIN_NAMES: dict[str, str] = {
    "bitcoin": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL", "ripple": "XRP",
    "cardano": "ADA", "dogecoin": "DOGE", "doge": "DOGE", "avalanche": "AVAX",
    "polkadot": "DOT", "chainlink": "LINK", "litecoin": "LTC", "bitcoin cash": "BCH",
    "uniswap": "UNI", "cosmos": "ATOM", "stellar": "XLM", "ethereum classic": "ETC",
    "aptos": "APT", "arbitrum": "ARB", "optimism": "OP", "filecoin": "FIL",
    "aave": "AAVE", "algorand": "ALGO", "sui": "SUI", "injective": "INJ",
}
BULLISH = ["long", "longing", "longed", "buy", "buying", "bought", "accumulate", "accumulating",
           "bullish", "breakout", "pump", "pumping", "moon", "mooning", "send it", "sending",
           "bottom is in", "bottomed", "undervalued", "going higher", "up only", "higher",
           "target", "targets", "entry", "entries", "load", "loading", "loaded", "dip",
           "bid", "bidding", "ape", "aping", "rip", "ripping", "🚀", "📈", "🟢", "💚"]
BEARISH = ["short", "shorting", "shorted", "sell", "selling", "sold", "bearish", "dump",
           "dumping", "top is in", "topped", "overvalued", "going lower", "lower", "exit",
           "exited", "take profit", "took profit", "tp", "rug", "crash", "crashing", "bleed",
           "bleeding", "nuke", "nuking", "📉", "🔻", "🩸", "🔴"]


def _phrases(text: str, words: list[str]) -> int:
    hits = 0
    for w in words:
        if w.isalpha() and w.isascii():
            hits += len(re.findall(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text))
        else:
            hits += text.count(w)
    return hits


def mentioned_coins(text: str, symbols: list[str]) -> list[str]:
    """Arena symbols the text names, in order of first appearance; only
    symbols the colony trades. A ticker counts as $BTC or as BTC in
    capitals (so "near the top" is not a call on NEAR); a name (bitcoin,
    solana) counts in any case."""
    low = text.lower()
    found: dict[str, int] = {}
    base_of = {}
    for sym in symbols:
        base = sym[:-4] if sym.endswith("USDT") else sym[:-3] if sym.endswith("USD") else sym
        base_of[base] = sym
    for base, sym in base_of.items():
        m = re.search(rf"(?<![A-Za-z0-9])(?:\${re.escape(base)}|{re.escape(base.upper())})"
                      rf"(?![A-Za-z0-9])", text, flags=0)
        if m is None:
            m = re.search(rf"(?<![a-z0-9])\${re.escape(base.lower())}(?![a-z0-9])", low)
        if m:
            found[sym] = min(found.get(sym, m.start()), m.start())
    for name, base in COIN_NAMES.items():
        sym = base_of.get(base)
        if sym is None:
            continue
        m = re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", low)
        if m:
            found[sym] = min(found.get(sym, m.start()), m.start())
    return [sym for sym, _ in sorted(found.items(), key=lambda kv: kv[1])]


def parse_calls(post: Post, symbols: list[str]) -> list[Call]:
    """The calls a post makes: every coin it names, with the direction the
    wording leans. A post that names no coin, or leans neither way, makes
    no call — the ledger only judges what can be judged."""
    coins = mentioned_coins(post.text, symbols)
    if not coins:
        return []
    low = post.text.lower()
    lean = _phrases(low, BULLISH) - _phrases(low, BEARISH)
    if lean == 0:
        return []
    side = 1 if lean > 0 else -1
    excerpt = re.sub(r"\s+", " ", post.text).strip()[:200]
    return [Call(post.source, post.post_id, post.ts, sym, side, excerpt, post.url)
            for sym in coins]


# ------------------------------------------------------------------ trust
def trust(source: Source, resolved: int, hits: int) -> float:
    """The weight a source's calls carry, from its own record: the prior
    until `min_resolved` calls are judged, blended towards 2 * hit_rate - 1
    as the record grows. In [-1, 1]; negative means 'do the opposite'."""
    if resolved <= 0:
        return source.prior
    measured = 2 * hits / resolved - 1
    w = min(resolved / max(source.min_resolved, 1), 1.0)
    return max(-1.0, min(1.0, (1 - w) * source.prior + w * measured))


def signals(calls: list[Call], weights: dict[str, float]) -> dict[str, float]:
    """Per symbol, the sum of the active calls' direction times their
    source's trust, clipped to [-1, 1]. `weights` maps handle -> trust."""
    out: dict[str, float] = {}
    for c in calls:
        out[c.symbol] = out.get(c.symbol, 0.0) + c.side * weights.get(c.source, 0.0)
    return {sym: round(max(-1.0, min(1.0, v)), 4) for sym, v in out.items()}


# ------------------------------------------------------------------ the X API
X_API = "https://api.x.com/2"


def fetch_x_posts(handle: str, bearer: str, since_id: str | None = None,
                  user_id: str | None = None, limit: int = 10,
                  timeout: int = 20) -> tuple[str, list[Post]]:
    """Recent original posts of `handle` via the X API v2 (pay-per-use:
    a fraction of a cent per post read). Returns (user_id, posts, newest
    last); pass the user_id back to skip the lookup next time."""
    def get(path: str, **params) -> dict:
        url = f"{X_API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}",
                                                   "User-Agent": "cryptoarena/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    if not user_id:
        user_id = get(f"/users/by/username/{handle}")["data"]["id"]
    params = {"max_results": max(5, min(limit, 100)), "exclude": "retweets,replies",
              "tweet.fields": "created_at"}
    if since_id:
        params["since_id"] = since_id
    data = get(f"/users/{user_id}/tweets", **params).get("data") or []
    from datetime import datetime
    posts = []
    for row in data:
        ts = int(datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).timestamp())
        posts.append(Post(handle, str(row["id"]), ts, row.get("text", ""),
                          f"https://x.com/{handle}/status/{row['id']}"))
    posts.sort(key=lambda p: int(p.post_id))
    return user_id, posts


def post_id_from_url(url: str) -> str | None:
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else None
