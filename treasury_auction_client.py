"""Treasury note/bond auction demand tracker -- indirect-bidder share and
bid-to-cover trend as an early rate-market-stress signal (FSI L2).

When foreign/institutional buyers (indirect bidders) pull back and
bid-to-cover falls, that's usually the earliest visible sign of rate-market
stress -- it shows up weeks before the yield/spread badges already on the
strip move. Source: treasurydirect.gov's own public JSON endpoint (US
Treasury, no signup, no key), same government-open-data trust boundary as
the existing FRED-sourced badges.

Distinct from the yield-curve (#170, pure rate-level arithmetic) and
credit-OAS (#230, corporate-spread) badges -- this tracks *demand* for the
debt, not its price/spread.
"""
import statistics
import time

import requests

_CACHE_TTL_S = 3600  # 1h, auctions are infrequent (roughly quarterly per term)
_cache: dict = {"computed_at": 0.0, "data": None}

_BASE_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
_TERMS = {"10-Year": "Note", "30-Year": "Bond"}


def _fetch_term_auctions(term: str, security_type: str, limit: int = 8) -> list[dict]:
    r = requests.get(_BASE_URL, params={"format": "json", "type": security_type, "days": 800}, timeout=15)
    r.raise_for_status()
    records = [d for d in r.json() if d.get("securityTerm") == term]
    records.sort(key=lambda d: d.get("auctionDate", ""))
    return records[-limit:]


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/trend against the trailing window
    (excluding the latest point). Same shape as copper_gold_ratio.py's
    _trend() helper."""
    if len(series) < 4:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def _classify_demand(indirect_share_trend: dict, bid_to_cover_trend: dict) -> str:
    if indirect_share_trend["direction"] == "falling" and bid_to_cover_trend["direction"] == "falling":
        return "weak"
    if indirect_share_trend["direction"] == "rising" and bid_to_cover_trend["direction"] != "falling":
        return "strong"
    return "normal"


def _compute_for_term(term: str, security_type: str) -> dict | None:
    auctions = _fetch_term_auctions(term, security_type)
    if len(auctions) < 4:
        return None

    indirect_shares, btc_ratios = [], []
    for a in auctions:
        total_accepted = a.get("totalAccepted")
        indirect_accepted = a.get("indirectBidderAccepted")
        btc = a.get("bidToCoverRatio")
        if not total_accepted or indirect_accepted is None or btc is None:
            continue
        indirect_shares.append(float(indirect_accepted) / float(total_accepted) * 100)
        btc_ratios.append(float(btc))

    if len(indirect_shares) < 4:
        return None

    indirect_trend = _trend(indirect_shares)
    btc_trend = _trend(btc_ratios)
    if indirect_trend is None or btc_trend is None:
        return None

    return {
        "term": term,
        "auction_date": auctions[-1].get("auctionDate", "")[:10],
        "indirect_bidder_share_pct": round(indirect_shares[-1], 2),
        "indirect_share_trend": indirect_trend,
        "bid_to_cover": round(btc_ratios[-1], 2),
        "bid_to_cover_trend": btc_trend,
        "demand": _classify_demand(indirect_trend, btc_trend),
    }


def compute_treasury_auction_demand() -> dict | None:
    """{"terms": {"10-Year": {...}, "30-Year": {...}}, "demand": "weak"/"normal"/"strong"}
    (overall demand takes the weaker of the two terms), or None if neither
    term has enough auction history to classify."""
    results = {}
    for term, security_type in _TERMS.items():
        try:
            data = _compute_for_term(term, security_type)
        except (requests.RequestException, ValueError):
            data = None
        if data:
            results[term] = data

    if not results:
        return None

    order = {"weak": 0, "normal": 1, "strong": 2}
    overall = min((r["demand"] for r in results.values()), key=lambda d: order[d])

    return {"terms": results, "demand": overall}


def get_treasury_auction_demand(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_treasury_auction_demand()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
