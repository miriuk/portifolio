"""Trading 212's public API (v0) on the PRACTICE account only.

The practice ("demo") account trades virtual money at real market prices.
This client knows one host, demo.trading212.com, and nothing else: there
is no setting, variable or argument that points it at a real account.

- Authentication: HTTP Basic, the API key as user and the API secret as
  password. Keys are made in the Trading 212 app with the Practice
  account selected, and read only from the environment (T212_API_KEY,
  T212_API_SECRET: GitHub secrets), never from files or arguments.
- Only stocks and ETFs; orders by quantity (fractions allowed); the API
  has no quote endpoint.
- The market-order endpoint is not idempotent (sent twice, it fills
  twice). `market_order` never retries after a timeout or a dropped
  connection (it raises `OrderUncertain`), only after a 429, which the
  rate limiter returns before the order reaches the book.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

DEMO = "https://demo.trading212.com/api/v0/equity"


class T212Error(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class OrderUncertain(RuntimeError):
    """The order may or may not have reached Trading 212: send nothing
    more until the account has been read again."""


class PracticeAccount:
    base = DEMO

    def __init__(self, key: str, secret: str, opener: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, timeout: int = 30):
        if not key or not secret:
            raise ValueError("the practice account needs T212_API_KEY and T212_API_SECRET")
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        self._auth = f"Basic {token}"
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._timeout = timeout

    @classmethod
    def from_env(cls, env: dict | None = None) -> "PracticeAccount":
        e = env if env is not None else os.environ
        return cls(e.get("T212_API_KEY", ""), e.get("T212_API_SECRET", ""))

    # -------------------------------------------------------------- transport
    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        req = urllib.request.Request(
            url, data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={"Authorization": self._auth, "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "cryptoarena/1.0"})
        try:
            with self._open(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
            raise T212Error(exc.code, detail or str(exc.reason)) from None
        return json.loads(raw) if raw else None

    def _get(self, path: str, query: dict | None = None, attempts: int = 3):
        for attempt in range(attempts):
            try:
                return self._call("GET", path, query=query)
            except T212Error as exc:
                if exc.status != 429 or attempt == attempts - 1:
                    raise
                self._sleep(6 * (attempt + 1))
        raise RuntimeError("unreachable")

    # -------------------------------------------------------------- reads
    def account_summary(self) -> dict:
        return self._get("/account/summary")

    def positions(self) -> list[dict]:
        return self._get("/positions") or []

    def instruments(self) -> list[dict]:
        return self._get("/metadata/instruments") or []

    def pending_orders(self) -> list[dict]:
        return self._get("/orders") or []

    # -------------------------------------------------------------- the one write
    def market_order(self, ticker: str, quantity: float) -> dict:
        """Buy (quantity > 0) or sell (< 0) at market, on the practice account."""
        if not quantity:
            raise ValueError("quantity must be non-zero")
        body = {"ticker": ticker, "quantity": quantity, "extendedHours": False}
        for attempt in range(2):
            try:
                return self._call("POST", "/orders/market", body)
            except T212Error as exc:
                if exc.status == 429 and attempt == 0:
                    self._sleep(65)
                    continue
                if exc.status in (408, 500, 502, 503, 504):
                    raise OrderUncertain(str(exc)) from None
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise OrderUncertain(f"no answer after sending the order: {exc}") from None
        raise RuntimeError("unreachable")
