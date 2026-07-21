"""SEC EDGAR Form 13F-HR institutional-manager holdings.

Managers with >$100M AUM must disclose long equity positions quarterly via
Form 13F-HR. Same free EDGAR REST conventions as sec_client.py's Form 4
integration, just a different form type and a curated list of well-known
managers instead of per-ticker lookups.

13F filings report issuer/CUSIP, not ticker symbols -- there's no free,
authoritative CUSIP->ticker mapping, so tickers are resolved by matching the
filing's issuer name against SEC's own company_tickers.json titles (both
normalized). Unmatched issuers are still stored (name + CUSIP) but with a
null ticker rather than a guessed one, per the no-fabricated-data principle.

SEC's fair-use policy requires a descriptive User-Agent with contact info
and caps sustained traffic -- kept to one request per filing, no concurrency.
"""
import re
import xml.etree.ElementTree as ET

import requests

_HEADERS = {"User-Agent": "FredAI research contact@example.com"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/index.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/{doc}"

# Curated well-known institutional managers (v1 -- not user-configurable).
# CIKs verified live against data.sec.gov/submissions.
MANAGERS = {
    "Berkshire Hathaway": "0001067983",
    "Renaissance Technologies": "0001037389",
    "Bridgewater Associates": "0001350694",
    "Scion Asset Management": "0001649339",
    "Citadel Advisors": "0001423053",
}

_NAME_STOPWORDS = {
    "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LLC",
    "PLC", "THE", "HOLDINGS", "HOLDING", "GROUP", "COM", "CLASS", "A", "B",
}

_name_to_ticker: dict[str, str] | None = None


def _normalize_issuer(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9 ]", "", name.upper())
    tokens = [t for t in cleaned.split() if t not in _NAME_STOPWORDS]
    return " ".join(tokens)


def _load_name_map() -> dict[str, str]:
    global _name_to_ticker
    if _name_to_ticker is not None:
        return _name_to_ticker
    try:
        r = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        _name_to_ticker = {}
        for v in r.json().values():
            key = _normalize_issuer(v["title"])
            if key:
                _name_to_ticker.setdefault(key, v["ticker"])
    except Exception as e:
        print(f"[SEC13F] Failed to load ticker name map: {e}")
        _name_to_ticker = {}
    return _name_to_ticker


def _ticker_for_issuer(issuer_name: str | None) -> str | None:
    if not issuer_name:
        return None
    return _load_name_map().get(_normalize_issuer(issuer_name))


def _find_info_table_doc(cik_short: str, accession_nodash: str) -> str | None:
    """The information table's filename is assigned by EDGAR per-filing (no
    fixed name) -- find it by elimination from the filing's own directory
    listing: everything except the cover-page primary_doc.xml and the
    index/full-submission files."""
    try:
        url = _FILING_INDEX_URL.format(cik_short=cik_short, accession_nodash=accession_nodash)
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        for item in r.json()["directory"]["item"]:
            name = item["name"]
            if name.lower().endswith(".xml") and name != "primary_doc.xml":
                return name
    except Exception as e:
        print(f"[SEC13F] Filing index fetch failed: {e}")
    return None


def _tag(el) -> str:
    return el.tag.split("}")[-1]


def _parse_info_table_xml(xml_text: str, manager: str, cik: str, filing_period: str | None) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    holdings = []
    for info in root:
        if _tag(info) != "infoTable":
            continue
        fields = {_tag(child): child for child in info}
        issuer_el = fields.get("nameOfIssuer")
        cusip_el = fields.get("cusip")
        value_el = fields.get("value")

        shares = None
        shrs_el = fields.get("shrsOrPrnAmt")
        if shrs_el is not None:
            for child in shrs_el:
                if _tag(child) == "sshPrnamt" and child.text:
                    shares = float(child.text)

        issuer_name = issuer_el.text if issuer_el is not None else None
        holdings.append({
            "manager": manager,
            "cik": cik,
            "issuer": issuer_name,
            "ticker": _ticker_for_issuer(issuer_name),
            "cusip": cusip_el.text if cusip_el is not None else None,
            "shares": shares,
            "value_usd": float(value_el.text) if value_el is not None and value_el.text else None,
            "filing_period": filing_period,
        })
    return holdings


def fetch_13f_holdings(manager: str, cik: str, limit_holdings: int = 25) -> list[dict]:
    """Fetch and parse a manager's most recent 13F-HR filing.

    Returns up to `limit_holdings` positions, largest reported value first.
    Returns [] if no 13F-HR is on file or the info table can't be located.
    """
    try:
        r = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_HEADERS, timeout=15)
        r.raise_for_status()
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"[SEC13F] Submissions fetch failed for {manager}: {e}")
        return []

    forms = recent.get("form", [])
    idx13f = next((i for i, f in enumerate(forms) if f == "13F-HR"), None)
    if idx13f is None:
        return []

    accession = recent["accessionNumber"][idx13f].replace("-", "")
    filing_period = recent.get("reportDate", [None] * len(forms))[idx13f]
    cik_short = str(int(cik))

    doc = _find_info_table_doc(cik_short, accession)
    if not doc:
        return []

    try:
        url = _ARCHIVE_URL.format(cik_short=cik_short, accession_nodash=accession, doc=doc)
        r = requests.get(url, headers=_HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[SEC13F] Info table fetch failed for {manager} ({accession}): {e}")
        return []

    holdings = _parse_info_table_xml(r.text, manager, cik, filing_period)
    holdings.sort(key=lambda h: h["value_usd"] or 0, reverse=True)
    return holdings[:limit_holdings]
