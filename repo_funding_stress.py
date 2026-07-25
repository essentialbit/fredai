"""Repo funding-market stress signal: SOFR vs EFFR overnight spread.

SOFR (Secured Overnight Financing Rate, repo-market/Treasury-collateral
borrowing) and EFFR (Effective Fed Funds Rate, unsecured interbank borrowing)
normally track within a few basis points of each other. When repo-market
collateral demand spikes relative to available cash -- dealer balance-sheet
constraints, quarter-end effects, or a genuine funding squeeze -- SOFR jumps
above EFFR. This is the exact plumbing-stress pattern that preceded the
September 2019 and March 2020 repo-rate spikes, both well before broader
credit spreads showed distress. Distinct from every other shipped macro-strip
signal (OAS/2s10s track credit/rate-curve, NFCI/STLFSI4 are broad composite
indices, dollar index/Treasury auction demand track currency/issuance) --
none of them isolate short-term secured-funding plumbing specifically.

Same free fredgraph.csv fetch pattern as breakeven_inflation.py/jobless-claims
(no API key, no signup), same _trend() z-score shape reused across every
macro-strip badge for consistency.
"""
import csv
import io
import statistics
import time

import requests

_SOFR_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SOFR"
_EFFR_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=EFFR"
_CACHE_TTL_S = 3600  # both series update daily on business days; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/breakeven_inflation.py's _trend()."""
    if len(series) < 8:
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
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series(url: str) -> dict[str, float] | None:
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"[RepoFundingStress] HTTP {r.status_code} for {url}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[RepoFundingStress] fetch error: {e}")
        return None

    out = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out[date] = float(raw)
        except ValueError:
            continue  # FRED uses "." for missing observations (holidays/weekends)
    return out or None


def compute_repo_stress() -> dict | None:
    """{"spread_bps": float, "date": str, "change_wow_bps": float,
    "trend_20d": {...}, "regime": "rising"/"falling"/"stable"} where
    spread_bps = (SOFR - EFFR) in basis points, or None if either feed
    can't be fetched or there's too little overlapping history."""
    sofr = _fetch_series(_SOFR_URL)
    effr = _fetch_series(_EFFR_URL)
    if not sofr or not effr:
        return None

    shared_dates = sorted(d for d in sofr if d in effr)
    if len(shared_dates) < 21:
        return None

    spread_bps = [(sofr[d] - effr[d]) * 100 for d in shared_dates]
    trend_20d = _trend(spread_bps[-21:])
    if trend_20d is None:
        return None

    return {
        "spread_bps": round(spread_bps[-1], 1),
        "date": shared_dates[-1],
        "change_wow_bps": round(spread_bps[-1] - spread_bps[-2], 1),
        "trend_20d": trend_20d,
        "regime": trend_20d["direction"],
    }


def get_repo_stress(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_repo_stress()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
