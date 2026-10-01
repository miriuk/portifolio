"""The chief of staff: reads everything the desk did and calls the owner
only when a decision is needed. The rest runs on its own.

Every closed day the chief writes one note — the colony against the line
it has to beat (holding the floor's benchmark since the founding), what
was bought and sold, what the desk refused — and files it in the journal,
where the desk feed shows it. On top of the note, a short list of
*decisions*: situations the colony cannot settle by itself.

- `behind`: after `min_days`, the colony trails holding the benchmark by
  more than `behind_pts`. Keep going, pause, or just hold the index?
- `drawdown`: the colony is more than `drawdown` below what it was founded
  with.
- `pm_ahead`: the PM's shadow book leads the colony by more than
  `pm_lead` since it opened. Should the mirror follow the PM?
- `stale`: no new bar for `stale_days`: the feed is broken or the job is.

`sync_issues` turns decisions into GitHub issues on the repository: one
issue per kind, opened when it first appears, its body kept current while
it stands, closed with a note when it clears. Nothing is posted when there
is nothing to decide.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

LABEL = "mesa"


@dataclass
class ChiefPolicy:
    benchmark: str = "SPY"           # the line to beat: hold this from the founding
    min_days: int = 10               # colony days before "behind" can be called
    behind_pts: float = 0.03         # trailing the benchmark by this much asks for a decision
    drawdown: float = 0.05           # below the founding capital by this much asks for one too
    pm_lead: float = 0.02            # the PM's book ahead of the colony by this much
    stale_days: float = 4.0          # no new bar for this long: something is broken


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pct(x: float | None) -> str:
    return "n/d" if x is None else f"{x:+.2%}"


def bench_start(tape: dict, symbol: str, started_at: str | None) -> dict | None:
    """The benchmark's close on the colony's first bar (the founding)."""
    rows = tape.get(symbol) or []
    if not rows:
        return None
    ts0 = int(datetime.fromisoformat(started_at).timestamp()) if started_at else None
    row = next((r for r in rows if ts0 is not None and int(r[0]) >= ts0), rows[0])
    return {"symbol": symbol, "ts": int(row[0]), "price": float(row[4])}


def day_activity(journal, day: int) -> dict:
    """What happened on colony day `day`: trades, the desk's refusals, and
    the events worth a line."""
    q = journal._conn.execute
    buys = q("SELECT symbol, COUNT(*), SUM(quantity * price) FROM trades WHERE episode = ? "
             "AND side = 'buy' GROUP BY symbol ORDER BY 3 DESC", (day,)).fetchall()
    sells = q("SELECT symbol, COUNT(*), SUM(quantity * price) FROM trades WHERE episode = ? "
              "AND side = 'sell' GROUP BY symbol ORDER BY 3 DESC", (day,)).fetchall()
    events = q("SELECT agent_id, event, detail FROM survival_events WHERE day = ? AND event IN "
               "('vetoed', 'clipped', 'born', 'died', 'retired', 'senior', 'employee_of_week')"
               " ORDER BY id", (day,)).fetchall()
    return {"buys": [(s, n, v) for s, n, v in buys], "sells": [(s, n, v) for s, n, v in sells],
            "events": events}


def report(status: dict, activity: dict, start: dict | None, founding: float,
           policy: ChiefPolicy, now: float | None = None) -> dict:
    """The day's note and the decisions it raises, from the colony's status."""
    day = max(int(status.get("day", 1)) - (1 if status.get("hour", 0) == 0 else 0), 0)
    equity = float(status.get("colony_equity") or 0.0)
    colony_ret = equity / founding - 1 if founding else None
    price = (status.get("prices") or {}).get(policy.benchmark)
    hold_ret = price / start["price"] - 1 if start and price else None
    gap = colony_ret - hold_ret if colony_ret is not None and hold_ret is not None else None

    lines = [f"Colônia {_money(equity)} ({_pct(colony_ret)} desde a fundação, {day} dias); "
             f"segurar {policy.benchmark} no mesmo período: {_pct(hold_ret)}."]
    if activity["buys"] or activity["sells"]:
        parts = [f"comprou {sym} ({n}× {_money(v)})" for sym, n, v in activity["buys"]]
        parts += [f"vendeu {sym} ({n}× {_money(v)})" for sym, n, v in activity["sells"]]
        lines.append("Hoje a mesa " + ", ".join(parts) + ".")
    else:
        lines.append("Hoje ninguém operou.")
    refused = [e for e in activity["events"] if e[1] in ("vetoed", "clipped")]
    if refused:
        lines.append(f"O risco da mesa barrou ou cortou {len(refused)} ordem(ns): "
                     + "; ".join(f"{a} — {d.removeprefix('desk: ')}" for a, _, d in refused[:3]) + ".")
    for agent, event, detail in activity["events"]:
        if event in ("born", "died", "retired", "senior", "employee_of_week"):
            label = {"born": "contratado", "died": "dispensado", "retired": "aposentado",
                     "senior": "sênior da semana", "employee_of_week": "funcionário da semana"}
            lines.append(f"{agent}: {label[event]}" + (f" ({detail})" if detail else "") + ".")
    desk = status.get("desk") or {}
    pm = desk.get("pm") or {}
    pm_gap = None
    if pm.get("return") is not None and pm.get("colony_return") is not None:
        pm_gap = pm["return"] - pm["colony_return"]
        lines.append(f"O livro do PM (desde o dia {pm.get('since_day')}): {_pct(pm['return'])}, "
                     f"a colônia no mesmo período {_pct(pm['colony_return'])}.")

    decisions = []
    if gap is not None and day >= policy.min_days and gap < -policy.behind_pts:
        decisions.append({
            "key": "behind",
            "title": f"A colônia está {abs(gap):.1%} atrás de segurar {policy.benchmark}",
            "body": (f"Depois de {day} dias a colônia fez {_pct(colony_ret)} e segurar "
                     f"{policy.benchmark} desde a fundação fez {_pct(hold_ret)}: "
                     f"{abs(gap):.1%} atrás (o limite é {policy.behind_pts:.0%}).\n\n"
                     "Opções: (1) seguir e reavaliar no relatório do mês; (2) pausar o andar; "
                     f"(3) trocar a carteira por segurar {policy.benchmark}.")})
    if colony_ret is not None and colony_ret < -policy.drawdown:
        decisions.append({
            "key": "drawdown",
            "title": f"A colônia caiu {abs(colony_ret):.1%} desde a fundação",
            "body": (f"Patrimônio {_money(equity)} contra {_money(founding)} na fundação "
                     f"({_pct(colony_ret)}; o limite é {policy.drawdown:.0%}). "
                     f"Segurar {policy.benchmark} no mesmo período: {_pct(hold_ret)}.\n\n"
                     "Opções: seguir, pausar o andar, ou reduzir o tamanho (refundar menor).")})
    if pm_gap is not None and pm_gap > policy.pm_lead:
        decisions.append({
            "key": "pm_ahead",
            "title": f"O livro do PM está {pm_gap:.1%} à frente da colônia",
            "body": (f"Desde o dia {pm.get('since_day')}, o PM fez {_pct(pm['return'])} e a "
                     f"colônia {_pct(pm['colony_return'])}.\n\nOpção: o espelho da Trading 212 "
                     "passar a seguir o livro do PM em vez das carteiras dos agentes.")})
    last = status.get("last_candle")
    if last:
        age = ((now or datetime.now(timezone.utc).timestamp())
               - datetime.fromisoformat(last).timestamp()) / 86400
        if age > policy.stale_days:
            decisions.append({
                "key": "stale",
                "title": f"O andar está sem barra nova há {age:.0f} dias",
                "body": (f"Última barra: {last}. O workflow ou a fonte de dados parou; "
                         "veja a aba Actions do repositório.")})
    headline = lines[0] if not decisions else \
        f"{len(decisions)} decisão(ões) para você: " + "; ".join(d["title"] for d in decisions)
    return {"day": day, "headline": headline, "lines": lines, "decisions": decisions,
            "colony_return": colony_ret, "hold_return": hold_ret, "benchmark": policy.benchmark,
            "bench_start": start}


def format_note(note: dict) -> str:
    out = [note["headline"], ""] + [f"- {line}" for line in note["lines"]]
    for d in note["decisions"]:
        out += ["", f"## {d['title']}", "", d["body"]]
    return "\n".join(out)


# ------------------------------------------------------------------ GitHub issues
class GitHub:
    """The few REST calls the chief needs, with the workflow's token."""

    def __init__(self, repo: str, token: str, api: str = "https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api

    @classmethod
    def from_env(cls) -> "GitHub | None":
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        return cls(repo, token) if repo and token else None

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{self.api}/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json", "User-Agent": "cryptoarena-chief"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    def ensure_label(self) -> None:
        try:
            self.call("POST", "/labels", {"name": LABEL, "color": "b08d57",
                                          "description": "decisions the chief of staff needs"})
        except urllib.error.HTTPError as exc:
            if exc.code != 422:                  # 422: it exists already
                raise

    def open_issues(self) -> list[dict]:
        return self.call("GET", f"/issues?state=open&labels={LABEL}&per_page=100") or []

    def create(self, title: str, body: str) -> dict:
        return self.call("POST", "/issues", {"title": title, "body": body, "labels": [LABEL]})

    def edit(self, number: int, **fields) -> dict:
        return self.call("PATCH", f"/issues/{number}", fields)

    def comment(self, number: int, body: str) -> dict:
        return self.call("POST", f"/issues/{number}/comments", {"body": body})


def _marker(floor: str, key: str) -> str:
    return f"<!-- mesa:{floor}:{key} -->"


def sync_issues(gh, floor: str, note: dict) -> list[str]:
    """One open issue per standing decision: open it when it appears, keep
    its body current while it stands, close it when it clears. Returns
    what was done, one line per action."""
    done = []
    standing = {d["key"]: d for d in note["decisions"]}
    open_by_key = {}
    for issue in gh.open_issues():
        for key in list(standing) + ["behind", "drawdown", "pm_ahead", "stale"]:
            if _marker(floor, key) in (issue.get("body") or ""):
                open_by_key[key] = issue
    for key, d in standing.items():
        body = (f"{_marker(floor, key)}\n**Andar:** {floor} · **dia {note['day']}**\n\n{d['body']}"
                "\n\n---\n_O chefe da mesa abre esta issue quando a situação aparece, atualiza "
                "enquanto ela dura e fecha quando ela some._")
        issue = open_by_key.get(key)
        if issue is None:
            if hasattr(gh, "ensure_label"):
                gh.ensure_label()
            made = gh.create(f"[{floor}] {d['title']}", body)
            done.append(f"opened #{made.get('number')}: {d['title']}")
        elif (issue.get("body") or "") != body:
            gh.edit(issue["number"], title=f"[{floor}] {d['title']}", body=body)
            done.append(f"updated #{issue['number']}")
    for key, issue in open_by_key.items():
        if key not in standing:
            gh.comment(issue["number"], f"A situação sumiu no dia {note['day']}: "
                                        f"{note['lines'][0]} Fechando.")
            gh.edit(issue["number"], state="closed")
            done.append(f"closed #{issue['number']}")
    return done


def safe_sync(gh, floor: str, note: dict) -> list[str]:
    """`sync_issues`, but a GitHub hiccup is reported, never raised: the
    colony is already saved and tomorrow's run tries again."""
    try:
        return sync_issues(gh, floor, note)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        return [f"GitHub issues not updated: {exc}"]
