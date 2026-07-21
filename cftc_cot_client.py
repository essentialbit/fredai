"""CFTC Commitment of Traders (COT) -- large-speculator positioning-extremes
badge, FSI L2 market-structure signal.

Every week the CFTC publishes a breakdown of futures open interest by
trader class (large speculators / commercial hedgers / small traders) for
every US-listed futures market. A crowded one-sided bet by large
speculators -- an extreme net-long or net-short position relative to its
own history -- has a long-documented contrarian-signal history: it tends
to precede a reversal, since that side of the trade is the first to run
out of fresh buyers/sellers. Distinct from every other shipped positioning
signal: options put/call ratio (not yet shipped) reads options-market
hedging, Kalshi/NAAIM read prediction-market or survey sentiment, this
reads real futures-market money via CFTC's own weekly regulatory filing.

Free, keyless, Socrata JSON endpoint (publicreporting.cftc.gov), unlike
NAAIM/FINRA margin-debt (both capped at ~10-13 trailing rows with no free
archive) this dataset has multi-year history per contract, so the z-score
baseline is never capped -- confirmed live back to at least 2022 for
E-MINI S&P 500.
"""
import statistics
import time

import requests

_COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_CONTRACT_NAME = "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"
_HISTORY_WEEKS = 60  # >1yr of weekly reports -- plenty for a trailing z-score window
_CACHE_TTL_S = 21600  # 6h -- CFTC COT only updates weekly (Fridays)
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point). Same shape as every other shipped badge's
    _trend() helper."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 1.0:
        regime = "crowded_long"
    elif z < -1.0:
        regime = "crowded_short"
    else:
        regime = "neutral"
    return {"latest": round(latest, 0), "mean": round(mean, 1), "z_score": round(z, 2), "regime": regime}


def _fetch_report_rows() -> list[dict] | None:
    try:
        params = {
            "$where": f"market_and_exchange_names = '{_CONTRACT_NAME}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": _HISTORY_WEEKS,
        }
        r = requests.get(_COT_URL, params=params, timeout=15)
        if r.status_code != 200:
            print(f"[CftcCot] HTTP {r.status_code}")
            return None
        rows = r.json()
    except Exception as e:
        print(f"[CftcCot] fetch error: {e}")
        return None
    return rows or None


def compute_cot_positioning() -> dict | None:
    """{"latest_net_noncomm": float, "date": str, "trend": {...},
    "regime": "crowded_long"/"crowded_short"/"neutral"} or None if the feed
    can't be fetched or has too little history."""
    rows = _fetch_report_rows()
    if not rows or len(rows) < 8:
        return None

    # Rows arrive newest-first; reverse to oldest-first for the trend window.
    rows = list(reversed(rows))

    series = []
    for row in rows:
        try:
            net = float(row["noncomm_positions_long_all"]) - float(row["noncomm_positions_short_all"])
            series.append((row["report_date_as_yyyy_mm_dd"][:10], net))
        except (KeyError, TypeError, ValueError):
            continue
    if len(series) < 8:
        return None

    values = [v for _, v in series]
    trend = _trend(values)
    if trend is None:
        return None

    latest_date, latest_net = series[-1]

    return {
        "latest_net_noncomm": round(latest_net, 0),
        "date": latest_date,
        "trend": trend,
        "regime": trend["regime"],
    }


def get_cot_positioning(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_cot_positioning()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
