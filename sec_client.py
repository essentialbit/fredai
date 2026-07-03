"""SEC EDGAR Form 4 insider-trading signals.

Form 4 discloses officer/director/10%-owner transactions within 2 business
days. Open-market purchases ("P") are the highest-conviction bullish tell —
an insider spending their own money. Open-market sales ("S") are a much
noisier signal (diversification, taxes, pre-scheduled 10b5-1 plans are all
common non-bearish reasons) but still worth surfacing.

SEC's fair-use policy requires a descriptive User-Agent with contact info
and caps sustained traffic — kept to one request per filing, no concurrency.
"""
import time
import xml.etree.ElementTree as ET

import requests

_HEADERS = {"User-Agent": "FredAI research contact@example.com"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/{doc}"

# Standardized SEC Form 4 transaction codes worth surfacing as a real signal.
# P/S are open-market (highest conviction); others are largely compensation
# mechanics (grants, tax-withholding share deliveries, option exercises).
SIGNAL_CODES = {"P": "open_market_purchase", "S": "open_market_sale"}

_cik_map: dict[str, str] | None = None


def _load_cik_map() -> dict[str, str]:
    global _cik_map
    if _cik_map is not None:
        return _cik_map
    try:
        r = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        _cik_map = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in data.values()}
    except Exception as e:
        print(f"[SEC] Failed to load ticker->CIK map: {e}")
        _cik_map = {}
    return _cik_map


def _get_cik(ticker: str) -> str | None:
    return _load_cik_map().get(ticker.upper())


def _parse_form4_xml(xml_text: str, ticker: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    owner_name_el = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    owner_title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
    owner_name = owner_name_el.text if owner_name_el is not None else "Unknown"
    owner_title = owner_title_el.text if owner_title_el is not None else None

    transactions = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code_el = txn.find("./transactionCoding/transactionCode")
        date_el = txn.find("./transactionDate/value")
        shares_el = txn.find("./transactionAmounts/transactionShares/value")
        price_el = txn.find("./transactionAmounts/transactionPricePerShare/value")
        ad_code_el = txn.find("./transactionAmounts/transactionAcquiredDisposedCode/value")

        code = code_el.text if code_el is not None else None
        if code is None:
            continue
        transactions.append({
            "ticker": ticker.upper(),
            "owner_name": owner_name,
            "owner_title": owner_title,
            "transaction_date": date_el.text if date_el is not None else None,
            "transaction_code": code,
            "is_signal_code": code in SIGNAL_CODES,
            "signal_type": SIGNAL_CODES.get(code),
            "shares": float(shares_el.text) if shares_el is not None else None,
            "price_per_share": float(price_el.text) if price_el is not None else None,
            "acquired_disposed": ad_code_el.text if ad_code_el is not None else None,
        })
    return transactions


def fetch_form4_filings(ticker: str, limit: int = 5, delay_s: float = 0.2) -> list[dict]:
    """Fetch and parse the most recent Form 4 filings for a ticker.

    Returns a flat list of individual transactions (one filing can contain
    several). Returns [] if the ticker isn't SEC-registered (e.g. crypto,
    non-US listings) or no Form 4s are on file yet.
    """
    cik = _get_cik(ticker)
    if not cik:
        return []

    try:
        r = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"[SEC] Submissions fetch failed for {ticker}: {e}")
        return []

    forms = recent.get("form", [])
    idx4 = [i for i, f in enumerate(forms) if f == "4"][:limit]
    if not idx4:
        return []

    cik_short = str(int(cik))
    all_transactions = []
    for i, idx in enumerate(idx4):
        accession = recent["accessionNumber"][idx].replace("-", "")
        try:
            url = _ARCHIVE_URL.format(cik_short=cik_short, accession_nodash=accession, doc="form4.xml")
            r = requests.get(url, headers=_HEADERS, timeout=15)
            if r.status_code == 200:
                all_transactions.extend(_parse_form4_xml(r.text, ticker))
        except Exception as e:
            print(f"[SEC] Form 4 fetch failed for {ticker} ({accession}): {e}")
        if i < len(idx4) - 1:
            time.sleep(delay_s)

    return all_transactions
