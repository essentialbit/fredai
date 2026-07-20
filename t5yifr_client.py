"""5-Year, 5-Year Forward Inflation Expectation Rate (FRED T5YIFR) macro badge.

T5YIFR is the market-implied average inflation rate expected over the
five-year period starting five years from now (i.e. 2031-2036 as of this
writing) -- the specific long-run inflation-anchor gauge the FOMC itself
watches as a check on whether inflation expectations stay "well anchored"
near 2%. Distinct from every inflation-adjacent badge already shipped:
T10YIE (breakeven_inflation.py) blends near-term and long-run expectations
over a straight 10-year window and moves with near-term CPI/PCE surprises;
MICH (mich_inflation_expectations_client.py) is a household survey, not a
market-derived price; CPIAUCSL/PCEPI/PCEPILFE are realized prints, not
expectations at all. T5YIFR isolates the long-horizon anchor specifically
because it nets out near-term noise.

Same free fredgraph.csv fetch pattern as every other FRED-sourced badge --
never curl, see the documented HTTP/2 gotcha in project memory.
"""
import csv
import io
import statistics
import time

import requests

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T5YIFR"
_CACHE_TTL_S = 3600  # T5YIFR updates daily on business days; hourly refetch is plenty
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as breakeven_inflation.py's/copper_gold_ratio.py's _trend()."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "de-anchoring higher"
    elif z < -0.5:
        direction = "de-anchoring lower"
    else:
        direction = "anchored"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def _fetch_series() -> list[tuple[str, float]] | None:
    try:
        r = requests.get(_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[T5YIFR] HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[T5YIFR] fetch error: {e}")
        return None

    out = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out.append((date, float(raw)))
        except ValueError:
            continue  # FRED uses "." for missing observations (holidays/weekends)
    return out or None


def compute_t5yifr() -> dict | None:
    """{"latest": float, "date": str, "change_wow": float, "trend_20d": {...},
    "regime": "anchored"/"de-anchoring higher"/"de-anchoring lower"} or None
    if the feed can't be fetched or has too little history."""
    series = _fetch_series()
    if not series or len(series) < 21:
        return None

    values = [v for _, v in series]
    trend_20d = _trend(values[-21:])
    if trend_20d is None:
        return None

    latest_date, latest_val = series[-1]
    prev_val = series[-2][1]
    return {
        "latest": latest_val,
        "date": latest_date,
        "change_wow": round(latest_val - prev_val, 2),
        "trend_20d": trend_20d,
        "regime": trend_20d["direction"],
    }


def get_t5yifr(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_t5yifr()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
