"""SEC Form 4: insiders' open-market purchases become calls in the ledger."""
import json

from cryptoarena.market import sec

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0001045810</issuerCik><issuerTradingSymbol>NVDA</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rsOwnerCik>1</rsOwnerCik><rsOwnerName>Doe Jane</rsOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>0</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>180.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>181</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""
SALE_ONLY = FORM4.replace("<transactionCode>P</transactionCode>", "<transactionCode>M</transactionCode>")


def submissions(*rows):
    return {"filings": {"recent": {
        "form": [r[0] for r in rows], "accessionNumber": [r[1] for r in rows],
        "acceptanceDateTime": [r[2] for r in rows], "primaryDocument": [r[3] for r in rows]}}}


def test_only_open_market_purchases_count():
    buys = sec.purchases(FORM4)
    assert buys == [{"owner": "Doe Jane", "role": "director", "shares": 1000.0,
                     "price": 180.5, "value": 180500.0, "planned": False}]
    assert sec.purchases(SALE_ONLY) == []


def test_recent_form4_skips_amendments_other_forms_and_what_was_seen():
    subs = submissions(("4", "a-1", "2026-09-10T20:01:02.000Z", "xslF345X05/f.xml"),
                       ("4/A", "a-2", "2026-09-11T20:01:02.000Z", "f.xml"),
                       ("8-K", "a-3", "2026-09-12T20:01:02.000Z", "k.htm"),
                       ("4", "a-4", "2026-09-13T20:01:02.000Z", "xslF345X05/g.xml"))
    seen = sec.recent_form4(subs)
    assert [f["accession"] for f in seen] == ["a-1", "a-4"]
    assert [f["accession"] for f in sec.recent_form4(subs, since_ts=seen[0]["ts"])] == ["a-4"]
    assert sec.raw_xml_name("xslF345X05/g.xml") == "g.xml"


def test_fetch_calls_reads_the_raw_xml_and_moves_the_cursor():
    subs = submissions(("4", "0001-26-000001", "2026-09-10T20:01:02.000Z", "xslF345X05/buy.xml"),
                       ("4", "0001-26-000002", "2026-09-12T20:01:02.000Z", "xslF345X05/sell.xml"))
    asked = []

    def get(url):
        asked.append(url)
        if "submissions" in url:
            return json.dumps(subs).encode()
        return (FORM4 if url.endswith("/buy.xml") else SALE_ONLY).encode()

    now = 1_790_000_000
    calls, since = sec.fetch_calls(["NVDA", "SPY"], get=get, now=lambda: now, pause=0)
    assert len(calls) == 1
    c = calls[0]
    assert (c.source, c.symbol, c.side, c.post_id) == ("sec-form4", "NVDA", 1, "0001-26-000001")
    assert "Doe Jane (director) bought 1,000 NVDA for $180,500" in c.text
    assert c.url.endswith("/1045810/000126000001/")
    assert any(u.endswith("/000126000001/buy.xml") for u in asked)   # the raw XML, not the page
    assert set(since) == {"NVDA"}                                    # ETFs file no Form 4
    again, _ = sec.fetch_calls(["NVDA"], since=since, get=get, now=lambda: now, pause=0)
    assert again == []


def test_without_a_declared_contact_the_source_stays_quiet(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert sec.user_agent() is None
    import pytest
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec._get("https://data.sec.gov/submissions/CIK0000320193.json")


def test_the_live_colony_files_insider_calls_in_its_ledger(tmp_path, monkeypatch):
    from cryptoarena.arena.live_colony import LiveColony
    from cryptoarena.arena.survival import SurvivalConfig
    from cryptoarena.cli import build_agents
    from cryptoarena.learning.memory import TradeJournal
    from cryptoarena.market.sources import Call, Source
    from test_live_colony import HOUR, T0, FakeClient, make_feed

    client = FakeClient()
    client.now = T0 + 120 * HOUR
    journal = TradeJournal(tmp_path / "live.db")
    src = [Source("sec-form4", "SEC Form 4", horizon_days=30)]
    colony = LiveColony.open(journal, build_agents(5.0, False, ""),
                             SurvivalConfig(budget=5.0, seed=1, endogenous=False),
                             make_feed(client), warmup=100, verbose=False, sources=src)
    ts = client.now - 3 * HOUR

    def fake(symbols, since=None, **kw):
        assert "BTCUSD" in symbols
        return [Call("sec-form4", "acc-1", ts, "BTCUSD", 1, "Form 4: …", "u")], {"BTCUSD": ts}
    monkeypatch.setattr(sec, "fetch_calls", fake)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    client.now += HOUR
    colony.run_once()
    assert journal.calls(source="sec-form4") == []              # no contact declared: quiet
    monkeypatch.setenv("SEC_USER_AGENT", "Test Person test@example.org")
    client.now += HOUR
    colony.run_once()
    calls = journal.calls(source="sec-form4")
    assert len(calls) == 1 and calls[0].price_at > 0
    assert colony.source_cursor["sec-form4"]["since"] == {"BTCUSD": ts}
    assert colony.signals()["BTCUSD"] > 0
    journal.close()
