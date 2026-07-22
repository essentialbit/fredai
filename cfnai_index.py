"""Chicago Fed National Activity Index (CFNAI) -- broad real-economic-
activity composite macro-strip badge.

CFNAI is a monthly composite of 85 economic indicators spanning production
and income, employment/unemployment/hours, personal consumption/housing,
and sales/orders/inventories, standardized so zero represents
trend-consistent growth. Distinct from NFCI (already shipped): NFCI tracks
financial/credit/liquidity conditions, CFNAI tracks real economic activity
breadth -- a different axis entirely.

The Chicago Fed's own published convention uses the 3-month moving average
(CFNAI-MA3) rather than the raw monthly print for regime calls, since the
single-month reading is noisy: CFNAI-MA3 below -0.7 following an expansion
signals an increasing likelihood of recession, above +0.7 signals rising
inflation pressure.

Same free fredgraph.csv fetch pattern already used by every other
FRED-sourced badge (NFCI, jobless claims, breakeven inflation) -- never
curl, see the documented HTTP/2 gotcha.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CFNAI"
_CACHE_TTL_S = 3600 * 6  # monthly-cadence data, matching durable_goods/totalsa
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as nfci_index.py's/copper_gold_ratio.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "strengthening"
    elif z < -0.5:
        direction = "weakening"
    else:
        direction = "stable"
    return {"latest": round(latest, 3), "mean": round(mean, 3), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[CFNAI] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[CFNAI] fetch error: {e}")
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


def compute_cfnai() -> dict | None:
    """{"latest": float, "ma3": float, "date": str, "trend_20d": {...},
    "regime": "recession_risk"/"below_trend"/"trend_growth"/"inflation_risk"}
    or None if the feed can't be fetched or has too little history.

    Regime bands follow the Chicago Fed's own published CFNAI-MA3
    thresholds (not an arbitrary z-score cut), same absolute-banding
    approach as nfci_index.py/epu_index.py."""
    series = _fetch_series()
    if not series or len(series) < 24:
        return None

    values = [v for _, v in series]
    ma3_series = [
        statistics.fmean(values[i - 2 : i + 1])
        for i in range(2, len(values))
    ]
    if len(ma3_series) < 21:
        return None

    trend_20d = _trend(ma3_series[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    latest_ma3 = round(ma3_series[-1], 3)

    if latest_ma3 < -0.7:
        regime = "recession_risk"
    elif latest_ma3 < 0.0:
        regime = "below_trend"
    elif latest_ma3 < 0.7:
        regime = "trend_growth"
    else:
        regime = "inflation_risk"

    return {
        "latest": round(latest_val, 3),
        "ma3": latest_ma3,
        "date": latest_date,
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_cfnai(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_cfnai()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
