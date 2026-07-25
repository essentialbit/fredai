"""CFTC Commitment of Traders (COT) — contrarian speculator-crowding signal (FSI L2).

Docs: https://publicreporting.cftc.gov/resource/6dca-aqww.json (Legacy COT report)
Public CFTC open-data endpoint, no key required. Same trust boundary as the
other free public market-data sources this app already reads.

Historically, one-sided noncommercial ("speculator") net positioning crowded
to an extreme relative to its own trailing range has preceded reversals —
this is a rolling z-score of net long/short vs. the trailing 52 weekly reports.
"""
import requests
from datetime import datetime

COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# market_and_exchange_names -> exact CFTC contract identifiers, confirmed live
CONTRACTS = {
    "SP500_EMINI": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "GOLD": "GOLD - COMMODITY EXCHANGE INC.",
    "CRUDE_OIL_WTI": "WTI FINANCIAL CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
    "EUR_USD": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "UST_10Y": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
}

CACHE_TTL_SECONDS = 43200  # 12h — CFTC publishes this report weekly (Friday)
_cache: dict = {}
_cache_expiry: dict = {}


def _fetch_weeks(contract_name: str, weeks: int = 53) -> list[dict]:
    r = requests.get(
        COT_URL,
        params={
            "$limit": weeks,
            "$where": f"market_and_exchange_names='{contract_name}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
        },
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _net_position(row: dict) -> float | None:
    try:
        return float(row["noncomm_positions_long_all"]) - float(row["noncomm_positions_short_all"])
    except (KeyError, TypeError, ValueError):
        return None


def fetch_cot_positioning(contract: str) -> dict | None:
    """Rolling z-score of noncommercial net positioning vs. its trailing
    52-week range for a tracked contract key (see CONTRACTS)."""
    if contract not in CONTRACTS:
        return None

    now = datetime.utcnow().timestamp()
    if contract in _cache and _cache_expiry.get(contract, 0) > now:
        return _cache[contract]

    try:
        rows = _fetch_weeks(CONTRACTS[contract])
    except Exception as e:
        print(f"[COT] fetch error ({contract}): {e}")
        return None

    net_positions = [n for n in (_net_position(row) for row in rows) if n is not None]
    if len(net_positions) < 10:
        return None

    latest = net_positions[0]
    history = net_positions[1:] or net_positions
    mean = sum(history) / len(history)
    variance = sum((v - mean) ** 2 for v in history) / len(history)
    stdev = variance ** 0.5

    z_score = round((latest - mean) / stdev, 2) if stdev else 0.0

    if z_score >= 1.5:
        classification = "crowded_long"
    elif z_score <= -1.5:
        classification = "crowded_short"
    else:
        classification = "neutral"

    result = {
        "contract": contract,
        "report_date": rows[0].get("report_date_as_yyyy_mm_dd"),
        "net_position": int(latest),
        "z_score": z_score,
        "classification": classification,
        "weeks_sampled": len(net_positions),
    }
    _cache[contract] = result
    _cache_expiry[contract] = now + CACHE_TTL_SECONDS
    return result


def fetch_all_cot_positioning() -> dict:
    """Positioning readings for every tracked contract, keyed by contract."""
    out = {}
    for contract in CONTRACTS:
        reading = fetch_cot_positioning(contract)
        if reading:
            out[contract] = reading
    return out
