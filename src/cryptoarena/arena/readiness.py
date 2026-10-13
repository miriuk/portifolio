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
4. **mirror**: the Trading 212 practice account following the colony —
   no execution incident in its runs, and on average no more than
   `max_tracking` of the colony's position value left uncovered.

The clock is the rules' fingerprint (`fingerprint`): the floor's
configuration, who its founders are, the seatbelt the floor gives each,
and the code of their strategies, hashed. Any change to them — a new
agent, a bigger seatbelt, another target, an edited strategy — starts the
count again from the session that closes next. A change the hash cannot
see (how fills are priced, the desk, a helper the strategies call) is
declared by bumping `REVISION`. Nothing here can trade: the colony and
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
# trades (fills, the desk, the risk manager, a helper the strategies call)
REVISION = 1
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
    max_tracking: float = 0.05    # mean share of the colony's position value the account leaves uncovered
    min_mirror_runs: int = 20     # runs of the mirror before it can be judged


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


def fingerprint(cfg, founders, params: tuple[str, ...] | None = None) -> str:
    """A short hash of the floor's rules: its configuration (the values
    that differ from the defaults, so a new option added with a neutral
    default changes nothing; minus what varies between runs), every
    founder's id and kind, the `params` the floor imposes on it (all of
    them when None), the code of each kind, and `REVISION`."""
    defaults = {f.name: (f.default if f.default is not MISSING else
                         f.default_factory() if f.default_factory is not MISSING else MISSING)
                for f in fields(cfg)}
    config = {k: v for k, v in asdict(cfg).items()
              if k not in _NOT_RULES and (defaults.get(k, MISSING) is MISSING or v != defaults[k])}
    people, kinds = [], {}
    for f in sorted(founders, key=lambda a: a.agent_id):
        given = (f.get_params() if hasattr(f, "get_params") else None) or {}
        if params is not None:
            given = {k: v for k, v in given.items() if k in params}
        people.append([f.agent_id, type(f).__name__, given])
        kinds.setdefault(type(f).__name__, _code(type(f)))
    blob = json.dumps({"revision": REVISION, "config": config, "founders": people,
                       "code": kinds}, sort_keys=True, default=str)
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
    {ts, ok, problems, tracking, unlisted} per run of the mirror."""
    rows = [r for r in ledger if since_ts is not None and r[0] >= since_ts
            and r[1] and r[3]]
    days = max(len(rows) - 1, 0)                 # sessions after the baseline
    colony_ret = bench_ret = colony_fall = bench_fall = None
    if days >= 2:
        index = _chain(rows)
        colony_ret = index[-1] - 1
        bench_ret = rows[-1][3] / rows[0][3] - 1
        colony_fall = _max_fall(index)
        bench_fall = _max_fall([r[3] for r in rows])
    runs = [m for m in mirror_runs if since_ts is not None and m["ts"] >= since_ts]
    problems = sum(1 for m in runs if not m["ok"])
    gaps = [m["tracking"] for m in runs if m.get("tracking") is not None]
    tracking = sum(gaps) / len(gaps) if gaps else None
    paper = runs[-1].get("unlisted") if runs else None

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
         "met": (None if len(runs) < policy.min_mirror_runs else
                 problems == 0 and tracking is not None and tracking <= policy.max_tracking),
         "value": (f"{len(runs)} execuções do espelho, {problems} com problema"
                   + (f", {tracking:.1%} da posição descoberta em média" if tracking is not None
                      else "")
                   + (f", {paper:.0%} da carteira só no papel (fora da lista da corretora)"
                      if paper else "")
                   + (f" (julga a partir de {policy.min_mirror_runs})"
                      if len(runs) < policy.min_mirror_runs else ""))},
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
