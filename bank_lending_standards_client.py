"""Senior Loan Officer Opinion Survey (FRED DRTSCILM) bank lending
standards macro badge.

Every shipped credit-related badge so far (ICE BofA OAS, Moody's Baa/10Y,
SOFR-EFFR repo stress, NFCI, STLFSI4) prices credit risk from the *market*
side -- bond spreads and funding-market stress. None track whether banks
are actually willing to extend loans. DRTSCILM is the Federal Reserve's own
quarterly survey of senior loan officers: net percentage of domestic banks
reporting tighter standards for commercial and industrial loans to large
and middle-market firms. It is a leading indicator the FOMC watches closely
-- net tightening spiking sharply has preceded every recession since the
survey began, and it moves ahead of the credit-spread badges rather than
alongside them (banks tighten standards before spreads blow out).

Same free, keyless fredgraph.csv fetch pattern as every other FRED-sourced
badge -- never curl, see the documented HTTP/2 stream-reset gotcha in
project memory; plain requests.get matches every shipped FRED client's
real code path.

DRTSCILM's sign convention is *not* inverted the way BOPGSTB's is: a
higher reading directly means more banks are tightening (worse credit
availability), so a rising z-score correctly reads as "tightening" and a
falling one as "easing" -- the standard direction mapping, just relabeled
for what the series actually measures.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DRTSCILM"
_CACHE_TTL_S = 21600  # DRTSCILM updates quarterly; 6h refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential)."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "tightening"
    elif z < -0.5:
        direction = "easing"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[BankLendingStandards] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[BankLendingStandards] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out.append((date, float(raw)))
        except ValueError:
            continue  # FRED uses "." for missing observations
    return out or None


def compute_bank_lending_standards() -> dict | None:
    """{"latest": float (net pct of banks tightening), "date": str,
    "change_qoq": float, "trend_8q": {...}, "regime": "tightening"/
    "easing"/"stable"} or None if the feed can't be fetched or has too
    little history."""
    series = _fetch_series()
    if not series or len(series) < 9:
        return None

    values = [v for _, v in series]
    trend_8q = _trend(values[-9:])
    if trend_8q is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]

    return {
        "latest": round(latest_val, 2),
        "date": latest_date,
        "change_qoq": round(latest_val - prev_val, 2),
        "trend_8q": trend_8q,
        "regime": trend_8q["direction"],
    }


def get_bank_lending_standards(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_bank_lending_standards()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
