"""SEC EDGAR real-time 8-K material-event filing monitor.

Form 4 (sec_client.py) only covers individual insider trades and 13F only
covers quarterly institutional snapshots -- neither catches same-day
corporate material events (M&A, leadership change, bankruptcy, new debt,
guidance). SEC's "current filings" atom feed streams every 8-K the moment
it's indexed, each tagged with its Item number, straight from the
regulatory source.

Same fair-use posture as sec_client.py: descriptive User-Agent, one poll
per cycle, no concurrency.
"""
import re

import requests
import xml.etree.ElementTree as ET

from sec_client import _HEADERS, _load_cik_map

_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom&count=100"

_TITLE_RE = re.compile(r"^8-K\s*-\s*(.+?)\s*\((\d{10})\)")
_ITEM_RE = re.compile(r"Item\s+(\d+\.\d+):\s*([^<\n]+)")
_FILED_RE = re.compile(r"Filed:</b>\s*([\d-]+)")
_ACCNO_RE = re.compile(r"AccNo:</b>\s*([\d-]+)")

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Item codes that reliably correspond to market-moving corporate events.
# Everything else (routine exhibits, comp-plan filings, shareholder vote
# results) is real signal but low-priority -- stored, not alerted.
MATERIAL_ITEMS = {"1.01", "1.03", "2.01", "2.03", "4.01", "5.02", "7.01"}


def _cik_to_ticker() -> dict[str, str]:
    return {cik: ticker for ticker, cik in _load_cik_map().items()}


def fetch_current_8k_filings(tickers: set[str] | None = None) -> list[dict]:
    """Poll EDGAR's current-filings feed for 8-Ks, optionally filtered to a
    set of uppercase tickers. Returns [] on any fetch/parse failure -- this
    is a live poll of the last ~100 filings, not a backfill."""
    try:
        r = requests.get(_FEED_URL, headers=_HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[SEC-8K] Feed fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        print(f"[SEC-8K] Feed parse failed: {e}")
        return []

    cik_map = _cik_to_ticker()
    filings = []
    for entry in root.findall("a:entry", _ATOM_NS):
        title_el = entry.find("a:title", _ATOM_NS)
        summary_el = entry.find("a:summary", _ATOM_NS)
        if title_el is None or summary_el is None:
            continue

        m = _TITLE_RE.match(title_el.text or "")
        if not m:
            continue
        company, cik = m.group(1), m.group(2)

        ticker = cik_map.get(cik)
        if tickers is not None and (not ticker or ticker not in tickers):
            continue

        summary = summary_el.text or ""
        items = _ITEM_RE.findall(summary)
        if not items:
            continue
        filed_m = _FILED_RE.search(summary)
        accno_m = _ACCNO_RE.search(summary)
        if not accno_m:
            continue

        is_material = any(code in MATERIAL_ITEMS for code, _ in items)
        filings.append({
            "ticker": ticker,
            "company": company,
            "cik": cik,
            "accession_number": accno_m.group(1),
            "filed_date": filed_m.group(1) if filed_m else None,
            "item_codes": ",".join(code for code, _ in items),
            "item_summary": "; ".join(f"{code} {desc.strip()}" for code, desc in items),
            "signal_type": "material" if is_material else "routine",
        })
    return filings
