"""Economic Policy Uncertainty (EPU) Index -- news-based macro uncertainty
trend badge (Baker/Bloom/Davis, policyuncertainty.com).

Distinct signal type from every other macro badge already shipped: unlike
VIX term structure (options-implied vol), credit spreads (bond market) or
Copper/Gold (commodity ratio), EPU is a text-mining/news-frequency measure of
policy uncertainty itself -- an academically-established leading indicator
that tends to precede equity volatility spikes and corporate investment
pullbacks.

Free daily CSV, no signup, no API key (confirmed live: returns 1985-present).
The endpoint 403s on the default `requests` User-Agent, so a browser-like one
is required. Raw daily values are noisy day-to-day (index construction is a
raw news-article count, not smoothed), so a 7-day trailing average is taken
before the z-score/trend computation to avoid single-day noise dominating
the signal -- the index is normalized so the 1985-2009 average = 100, which
is what the calm/elevated/spike bands below are anchored to.
"""
import csv
import io
import statistics
import time

import requests

EPU_URL = "https://www.policyuncertainty.com/media/All_Daily_Policy_Data.csv"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

_CACHE_TTL_S = 900  # 15 min, matching sibling macro modules (copper_gold_ratio.py etc.)
_cache: dict = {"computed_at": 0.0, "data": None}


def _fetch_series(lookback_days: int = 90) -> list[float] | None:
    """Chronological list of the most recent `lookback_days` raw daily_policy_index
    values, or None on failure."""
    try:
        r = requests.get(EPU_URL, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"[EPU] HTTP {r.status_code}")
            return None
        reader = csv.reader(io.StringIO(r.content.decode("utf-8", errors="replace")))
        rows = list(reader)
    except Exception as e:
        print(f"[EPU] fetch error: {e}")
        return None

    values: list[float] = []
    for row in rows[1:]:
        if len(row) < 4 or not row[3].strip():
            continue
        try:
            values.append(float(row[3]))
        except ValueError:
            continue
    return values[-lookback_days:] if values else None


def _smooth(series: list[float], window: int = 7) -> list[float]:
    """Trailing moving average, one output value per input point once a full
    window is available."""
    return [statistics.fmean(series[i - window + 1:i + 1]) for i in range(window - 1, len(series))]


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/trend direction against the trailing
    window (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's/bitcoin_onchain_client.py's _trend()."""
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


def _period_change_pct(series: list[float], days: int) -> float | None:
    if len(series) < days + 1:
        return None
    start, end = series[-(days + 1)], series[-1]
    if not start:
        return None
    return (end - start) / start * 100


def compute_epu_index() -> dict | None:
    """{"value": float, "change_5d_pct": float, "trend_20d": {...}, "regime"}
    (regime is "calm"/"elevated"/"spike", banded off the smoothed level since
    the index is constructed with a fixed 1985-2009 average of 100), or None
    if the feed can't be fetched or there isn't enough history yet."""
    raw = _fetch_series()
    if not raw or len(raw) < 33:
        return None

    smoothed = _smooth(raw, window=7)
    if len(smoothed) < 21:
        return None

    trend_20d = _trend(smoothed[-21:])
    change_5d_pct = _period_change_pct(smoothed, 5)
    if trend_20d is None or change_5d_pct is None:
        return None

    latest = smoothed[-1]
    if latest < 120:
        regime = "calm"
    elif latest < 200:
        regime = "elevated"
    else:
        regime = "spike"

    return {
        "value": round(latest, 2),
        "change_5d_pct": round(change_5d_pct, 2),
        "trend_20d": trend_20d,
        "regime": regime,
    }


def get_epu_index(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_epu_index()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
