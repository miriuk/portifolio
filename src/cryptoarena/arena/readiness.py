"""The go / no-go scorecard for real money, agreed before the results.

The owner and the colony agreed on 13/10/2026, before seeing a single day
of results, what would have to be true before real money is even
discussed. Writing it down first is the point: a line drawn after the
results is drawn where they happen to be.

1. **time**: at least `min_days` sessions (about six months; `ideal_days`,
   a year, is better) under the *same* rules;
2. **return**: the colony ahead of holding the benchmark over those
   sessions, net of its own fees;
3. **fall**: the colony's worst fall from a high no deeper than the
   benchmark's over the same sessions;
4. **mirror**: the Trading 212 practice account following the colony,
   judged night by night — a night being every run between two market
   opens, so the 05:30 retry and any rerun fold into the night whose open
   they follow, and a night counts its worst measurement: at least
   `min_mirror_nights` nights measured, no order that failed or went
   unanswered, the account unreadable on no more than `max_missed` of the
   nights, and on average no more than `max_tracking` of what the previous
   night aimed at missing from the account.

The clock is the rules' fingerprint (`fingerprint`): the floor's
configuration, who its founders are, the seatbelt the floor gives each,
the code of their strategies, the sources they listen to, and this
policy itself, hashed. Any change to them — a new agent, a bigger
seatbelt, another target, an edited strategy, a criterion moved — starts
the count again from the session that closes next. The configuration is
compared with the snapshot the clock started with (`rules_config`), so
an option added later with a neutral default changes nothing. A change
the hash cannot see (how fills are priced, the desk, a helper the
strategies call) is declared by bumping `REVISION`. Nothing here can trade: the colony and
the mirror stay on paper and on the practice account, and meeting every
criterion only opens an issue for the owner to decide by hand.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import textwrap
from dataclasses import MISSING, asdict, dataclass, fields

# bump by hand when a change the fingerprint cannot see changes how the floor
# trades (fills, the desk, the risk manager, a helper the strategies call) or
# how the scorecard is measured. Every bump, and why:
#   2 (14/10/2026, owner's call): the mirror kept trying QQQ, which Trading 212
#     refuses to a UK account, so its first night counted as an incident; fixed
#     in broker/mirror.py, and the clock starts again with the fixed mirror
REVISION = 2
# what may vary between runs without being a change of rules
_NOT_RULES = {"days", "seed", "budget", "warmup_bars"}
# whose code counts: the strategies and their parents in this package (not
# the standard library's, which changes with the Python version)
_OWN = ("cryptoarena",)


@dataclass(frozen=True)
class ReadinessPolicy:
    benchmark: str = "SPY"
    min_days: int = 126           # about six months of sessions
    ideal_days: int = 252         # a year
    max_tracking: float = 0.05    # mean share of the previous night's aim missing from the account
    min_mirror_nights: int = 20   # nights the mirror is measured before it can be judged
    max_missed: float = 0.10      # share of the nights the account may be unreadable
    open_utc: float = 14.5        # hours: a night ends at the market open (NYSE, the later of its two UTC times)


def _code(cls: type) -> str:
    """The class and its parents in this package, as the interpreter runs
    them: comments, docstrings and layout do not count."""
    out = []
    for klass in cls.__mro__:
        if not klass.__module__.startswith(_OWN):
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(klass)))
        except (OSError, TypeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body
                    and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
        out.append(ast.unparse(tree))
    return hashlib.sha256("\n".join(out).encode()).hexdigest()[:16]


def _plain(value):
    return json.loads(json.dumps(value, default=str))


def rules_config(cfg, baseline: dict | None = None) -> dict:
    """The configuration the clock counts, as JSON: every field minus what
    varies between runs when the clock starts (`baseline` None); after
    that, the fields in the snapshot it started with plus any field added
    since whose value is not its neutral default."""
    current = _plain({k: v for k, v in asdict(cfg).items() if k not in _NOT_RULES})
    if baseline is None:
        return current
    defaults = {f.name: (f.default if f.default is not MISSING else
                         f.default_factory() if f.default_factory is not MISSING else MISSING)
                for f in fields(cfg)}
    return {k: v for k, v in current.items()
            if k in baseline or defaults.get(k, MISSING) is MISSING or v != _plain(defaults[k])}


def fingerprint(cfg, founders, params: tuple[str, ...] | None = None, sources=(),
                policy: "ReadinessPolicy | None" = None, quiet: tuple[str, ...] = ()) -> str:
    """A short hash of the floor's rules: its configuration (`cfg`, or a
    `rules_config` dict), every founder's id and kind, the `params` the
    floor imposes on it (all of them when None), the code of each kind,
    the sources' trust settings and which of them are `quiet` (configured
    but unable to read: SEC Form 4 without SEC_USER_AGENT), this policy,
    and `REVISION`. A quiet source coming alive changes what the agents
    see, so it starts the clock again too."""
    config = cfg if isinstance(cfg, dict) else rules_config(cfg)
    people, kinds = [], {}
    for f in sorted(founders, key=lambda a: a.agent_id):
        given = (f.get_params() if hasattr(f, "get_params") else None) or {}
        if params is not None:
            given = {k: v for k, v in given.items() if k in params}
        people.append([f.agent_id, type(f).__name__, given])
        kinds.setdefault(type(f).__name__, _code(type(f)))
    listen = sorted([s.handle, s.prior, s.horizon_days, s.min_resolved, s.handle in quiet]
                    for s in sources)
    blob = json.dumps({"revision": REVISION, "config": config, "founders": people,
                       "code": kinds, "sources": listen,
                       "policy": asdict(policy) if policy is not None else None},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _chain(ledger: list[list[float]]) -> list[float]:
    """The colony's value index over the ledger rows (ts, equity, founding,
    benchmark close), money added or withdrawn (a change in the founders'
    budgets) taken out so it does not count as return."""
    idx = [1.0]
    for prev, row in zip(ledger, ledger[1:]):
        flow = row[2] - prev[2]
        growth = (row[1] - flow) / prev[1] if prev[1] > 0 else 1.0
        idx.append(idx[-1] * growth)
    return idx


def _max_fall(values: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, 1 - v / peak)
    return worst


def scorecard(ledger: list[list[float]], since_ts: int | None, mirror_runs: list[dict],
              policy: ReadinessPolicy) -> dict:
    """The four criteria from `since_ts` on. `ledger` rows: [close ts,
    colony equity, founders' budget, benchmark close] per closed session,
    the first one the baseline the others are measured from; `mirror_runs`:
    {ts, problems, missed, tracking, unlisted} per run of the mirror."""
    rows = [r for r in ledger if since_ts is not None and r[0] >= since_ts
            and r[1] and r[3]]
    days = max(len(rows) - 1, 0)                 # sessions after the baseline
    colony_ret = bench_ret = colony_fall = bench_fall = None
    if days >= 1:
        index = _chain(rows)
        colony_ret = index[-1] - 1
        bench_ret = rows[-1][3] / rows[0][3] - 1
        colony_fall = _max_fall(index)
        bench_fall = _max_fall([r[3] for r in rows])
    runs = sorted((m for m in mirror_runs if since_ts is not None and m["ts"] >= since_ts),
                  key=lambda m: m["ts"])
    nights: dict[int, list[dict]] = {}
    cut = int(policy.open_utc * 3600)
    for m in runs:                                # the 01:30 run, the 05:30 retry, a rerun: one night
        nights.setdefault((int(m["ts"]) - cut) // 86400, []).append(m)
    bad = sum(1 for night in nights.values() if any(m.get("problems") for m in night))
    missed = sum(1 for night in nights.values() if all(m.get("missed") for m in night))
    gaps = [max(m["tracking"] for m in night if m.get("tracking") is not None)
            for night in nights.values() if any(m.get("tracking") is not None for m in night)]
    tracking = sum(gaps) / len(gaps) if gaps else None
    paper = next((m["unlisted"] for m in reversed(runs) if m.get("unlisted") is not None), None)
    missed_share = missed / len(nights) if nights else 0.0

    criteria = [
        {"key": "time", "label": "tempo sob as mesmas regras",
         "met": days >= policy.min_days,
         "value": f"{days} de {policy.min_days} pregões (ideal {policy.ideal_days})"},
        {"key": "return", "label": f"à frente de segurar {policy.benchmark}",
         "met": None if colony_ret is None else colony_ret > bench_ret,
         "value": ("sem dados ainda" if colony_ret is None else
                   f"colônia {colony_ret:+.2%} contra {policy.benchmark} {bench_ret:+.2%}")},
        {"key": "fall", "label": f"queda máxima não pior que a de {policy.benchmark}",
         "met": None if colony_fall is None else colony_fall <= bench_fall,
         "value": ("sem dados ainda" if colony_fall is None else
                   f"colônia {colony_fall:.1%} contra {policy.benchmark} {bench_fall:.1%}")},
        {"key": "mirror", "label": "conta Practice acompanhando, sem incidente",
         "met": (None if len(gaps) < policy.min_mirror_nights else
                 bad == 0 and missed_share <= policy.max_missed
                 and tracking <= policy.max_tracking),
         "value": (f"{len(nights)} noites do espelho ({len(gaps)} medidas), {bad} com ordem "
                   "falhada ou sem resposta"
                   + (f", {missed} sem conseguir ler a conta" if missed else "")
                   + (f", {tracking:.1%} do que a noite anterior mirou faltando em média"
                      if tracking is not None else "")
                   + (f", {paper:.0%} da carteira só no papel (fora da lista da corretora)"
                      if paper else "")
                   + (f" (julga a partir de {policy.min_mirror_nights} noites medidas)"
                      if len(gaps) < policy.min_mirror_nights else ""))},
    ]
    met = sum(1 for c in criteria if c["met"] is True)
    return {"since": since_ts, "days": days, "criteria": criteria, "met": met,
            "of": len(criteria), "ready": met == len(criteria),
            "colony_return": colony_ret, "benchmark_return": bench_ret}


def summary_line(card: dict) -> str:
    """One line for the chief's note."""
    marks = {True: "✅", False: "❌", None: "⏳"}
    parts = "; ".join(f"{marks[c['met']]} {c['label']}: {c['value']}" for c in card["criteria"])
    return f"Prontidão para dinheiro real: {card['met']} de {card['of']} critérios. {parts}."
