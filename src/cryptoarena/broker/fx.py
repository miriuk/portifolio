"""Pounds to dollars: the European Central Bank's daily reference rates,
through Frankfurter's JSON (no key) or the ECB's own XML."""
from __future__ import annotations

import json
import re
import urllib.request

FRANKFURTER = "https://api.frankfurter.app/latest?from=GBP&to=USD"
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cryptoarena/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_ecb(xml: str) -> float:
    """USD per GBP from the ECB's euro reference rates."""
    rates = dict(re.findall(r"currency='([A-Z]{3})' rate='([0-9.]+)'", xml))
    return float(rates["USD"]) / float(rates["GBP"])


def usd_per_gbp(fetch=_get) -> float:
    try:
        return float(json.loads(fetch(FRANKFURTER))["rates"]["USD"])
    except Exception:                  # noqa: BLE001 — then the ECB itself
        return parse_ecb(fetch(ECB).decode("utf-8", "replace"))
