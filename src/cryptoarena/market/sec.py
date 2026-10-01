"""Insiders buying their own company's stock: SEC Form 4 as a source.

When a director or officer of a US company trades its shares, they file a
Form 4 with the SEC within two business days, and EDGAR publishes it for
free. Sales say little (pay, taxes, diversification, pre-scheduled 10b5-1
plans); *open-market purchases* (transaction code P) are an insider
putting their own money in at the market price, and the academic record
gives them some predictive power (Lakonishok & Lee 2001; Cohen, Malloy &
Pomorski 2012), weaker in the largest companies. In mega caps like Apple
or Nvidia such purchases are rare: the source may stay silent for months.

Each purchase becomes a long *call* in the colony's sources ledger, filed
at the price on the tape when it was accepted, judged after the source's
horizon like any X account's call, and weighted by the trust its record
earns (market/sources.py). Nothing here trades by itself.

EDGAR asks every client for a User-Agent naming who is asking
(`SEC_USER_AGENT`), and at most ten requests a second.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from .sources import Call

SOURCE = "sec-form4"
# the stocks floor's companies (ETFs file no Form 4)
CIKS = {"AAPL": 320193, "MSFT": 789019, "NVDA": 1045810, "AMZN": 1018724}
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
DEFAULT_UA = "CryptoArena research bot (+https://github.com/miriuk/portifolio)"


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT") or DEFAULT_UA


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(),
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def recent_form4(submissions: dict, since_ts: int = 0) -> list[dict]:
    """The Form 4 filings (not amendments) in a company's submissions
    index accepted after `since_ts`, oldest first."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(recent.get("form", [])):
        if form != "4":
            continue
        accepted = recent["acceptanceDateTime"][i]
        ts = int(datetime.fromisoformat(accepted.replace("Z", "+00:00")).timestamp())
        if ts <= since_ts:
            continue
        out.append({"accession": recent["accessionNumber"][i], "ts": ts,
                    "document": recent["primaryDocument"][i]})
    return sorted(out, key=lambda f: f["ts"])


def raw_xml_name(document: str) -> str:
    """EDGAR lists the rendered page (xslF345X05/form4.xml); the raw XML is
    the same file name at the filing's root."""
    return document.rsplit("/", 1)[-1]


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _num(node, path: str) -> float:
    try:
        return float(_text(node, path) or 0)
    except ValueError:
        return 0.0


def purchases(xml: bytes | str) -> list[dict]:
    """Open-market purchases (code P, shares acquired) in one Form 4: who,
    their role, shares, price, value; and whether a 10b5-1 plan was ticked."""
    root = ET.fromstring(xml)
    owners = []
    for owner in root.findall("reportingOwner"):
        rel = owner.find("reportingOwnerRelationship")
        role = []
        if rel is not None:
            if _text(rel, "isDirector") in ("1", "true"):
                role.append("director")
            if _text(rel, "isOfficer") in ("1", "true"):
                role.append(_text(rel, "officerTitle") or "officer")
            if _text(rel, "isTenPercentOwner") in ("1", "true"):
                role.append("10% owner")
        owners.append((_text(owner, "reportingOwnerId/rsOwnerName"), ", ".join(role)))
    planned = _text(root, "aff10b5One") in ("1", "true")
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _text(tx, "transactionCoding/transactionCode") != "P":
            continue
        if _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") != "A":
            continue
        shares = _num(tx, "transactionAmounts/transactionShares/value")
        price = _num(tx, "transactionAmounts/transactionPricePerShare/value")
        if shares <= 0:
            continue
        name, role = owners[0] if owners else ("", "")
        out.append({"owner": name, "role": role, "shares": shares, "price": price,
                    "value": shares * price, "planned": planned})
    return out


def calls_for(symbol: str, cik: int, filing: dict, xml: bytes | str) -> list[Call]:
    """One long call per filing with at least one open-market purchase."""
    buys = purchases(xml)
    if not buys:
        return []
    value = sum(b["value"] for b in buys)
    shares = sum(b["shares"] for b in buys)
    who = buys[0]["owner"] + (f" ({buys[0]['role']})" if buys[0]["role"] else "")
    text = (f"Form 4: {who} bought {shares:,.0f} {symbol} for ${value:,.0f}"
            + (" under a 10b5-1 plan" if buys[0]["planned"] else ""))
    url = ARCHIVE.format(cik=cik, acc=filing["accession"].replace("-", ""))
    return [Call(SOURCE, filing["accession"], filing["ts"], symbol, +1, text, url)]


def fetch_calls(symbols: list[str], since: dict[str, int] | None = None,
                lookback_days: int = 60, get=_get, now=time.time,
                pause: float = 0.15) -> tuple[list[Call], dict[str, int]]:
    """New insider-purchase calls for the floor's companies since the last
    visit (`since`: symbol -> last acceptance seen; a first visit looks
    back `lookback_days`). Returns (calls, updated since)."""
    since = dict(since or {})
    calls: list[Call] = []
    for symbol in symbols:
        cik = CIKS.get(symbol)
        if cik is None:
            continue
        floor_ts = since.get(symbol) or int(now() - lookback_days * 86400)
        subs = json.loads(get(SUBMISSIONS.format(cik=cik)))
        filings = recent_form4(subs, floor_ts)
        for filing in filings:
            time.sleep(pause)                      # EDGAR: at most ten requests a second
            url = ARCHIVE.format(cik=cik, acc=filing["accession"].replace("-", "")) \
                + raw_xml_name(filing["document"])
            try:
                calls += calls_for(symbol, cik, filing, get(url))
            except ET.ParseError:
                continue
        if filings:
            since[symbol] = filings[-1]["ts"]
        else:
            since.setdefault(symbol, floor_ts)
    return calls, since
