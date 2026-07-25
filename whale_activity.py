"""Institutional "Whale Activity Index" (FSI L1/L2) -- a free-data proxy
for institutional block/sweep activity.

No free source for real options block-sweep or dark-pool print-by-print
data exists (confirmed during research -- that granularity is a paid
feed: Unusual Whales, FlowAlgo, etc.). This composite instead blends two
real, free, keyless FINRA public data sources already in this codebase:
daily Reg SHO short-volume ratio (finra_short_volume.py) and weekly
off-exchange/ATS volume (dark_pool_client.py), both z-scored against
their own trailing baseline. Labeled honestly as a FINRA-volume proxy,
not literal block-print data -- same data-correctness discipline as the
#140/BOPGSTB precedent elsewhere in this codebase.

Dark pool data specifically carries a ~2-3 week publication lag
(documented in dark_pool_client.py) -- this composite is never presented
as a same-day reading.
"""
from finra_short_volume import compute_short_volume_signal
from dark_pool_client import get_dark_pool_signal


def compute_whale_activity(ticker: str) -> dict | None:
    """{"ticker", "whale_index": 0-100, "band", "short_volume", "dark_pool"}.
    None only if BOTH sources have no signal yet -- a partial signal (one
    source missing, e.g. a newly-watched ticker with <8 days of short-volume
    history but enough dark-pool weeks) still returns a result using
    whichever z-score is available, rather than requiring both."""
    sv = compute_short_volume_signal(ticker)
    dp = get_dark_pool_signal(ticker)

    sv_z = sv["trend"]["z_score"] if sv and sv.get("trend") else None
    dp_z = dp["trend"]["z_score"] if dp and dp.get("trend") else None

    zs = [z for z in (sv_z, dp_z) if z is not None]
    if not zs:
        return None
    avg_z = sum(zs) / len(zs)

    whale_index = round(max(0.0, min(100.0, 50 + 12.5 * avg_z)), 1)
    if whale_index >= 65:
        band = "elevated"
    elif whale_index <= 35:
        band = "subdued"
    else:
        band = "normal"

    return {
        "ticker": ticker.upper(),
        "whale_index": whale_index,
        "band": band,
        "short_volume": sv,
        "dark_pool": dp,
    }
