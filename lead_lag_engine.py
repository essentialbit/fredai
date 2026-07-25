"""Cross-asset lead-lag detector (FSI L2) -- Granger causality over a small,
curated set of macro-to-market pairs, not an open-ended pairwise scan.

Uses statsmodels.tsa.stattools.grangercausalitytests: does the leader
series' past values help predict the follower series, beyond what the
follower's own past predicts? Tested at lags 1-5 trading days on daily
return series; the lag with the lowest p-value is reported as the "lead
time", flagged significant if p < 0.05.

Yield-curve leg uses the TLT/SHY (long-vs-short Treasury ETF) price ratio
as a free, keyless curve-steepness proxy -- fetchable through the same
Yahoo chart path as every other macro badge (see copper_gold_ratio.py),
rather than nasdaq_client.get_macro_snapshot()'s API-key-gated Treasury
yield snapshot, which is also a single current value, not a time series,
so unusable for a lagged causality test as-is.
"""
import contextlib
import io
import time

import numpy as np
from statsmodels.tsa.stattools import grangercausalitytests

from market_data import fetch_history

_CACHE_TTL_S = 21600  # 6h, matches other daily-resolution macro badges
_MAX_LAG = 5
_ALPHA = 0.05
_MIN_RETURNS = 30

_PAIRS = (
    {"name": "copper_gold_to_spy", "leader": ("CPER", "GLD"), "follower": "SPY",
     "label": "Copper/Gold ratio -> SPY"},
    {"name": "curve_steepness_to_xlf", "leader": ("TLT", "SHY"), "follower": "XLF",
     "label": "TLT/SHY (curve steepness proxy) -> XLF"},
    {"name": "vix_to_spy", "leader": ("^VIX", None), "follower": "SPY",
     "label": "VIX -> SPY"},
)

_cache: dict = {"computed_at": 0.0, "data": None}


def _closes(ticker: str, period: str = "6mo") -> list[float] | None:
    h = fetch_history(ticker, period=period, interval="1d")
    if not h:
        return None
    closes = [r["close"] for r in h if r.get("close") is not None]
    return closes or None


def _returns(series: list[float]) -> list[float]:
    return [(series[i] - series[i - 1]) / series[i - 1] for i in range(1, len(series)) if series[i - 1]]


def _leader_series(leader_spec: tuple) -> list[float] | None:
    """Either a single ticker's close series, or the ratio of two (e.g.
    CPER/GLD, TLT/SHY) when the second element isn't None."""
    a, b = leader_spec
    a_closes = _closes(a)
    if a_closes is None:
        return None
    if b is None:
        return a_closes
    b_closes = _closes(b)
    if b_closes is None:
        return None
    n = min(len(a_closes), len(b_closes))
    ratio = [x / y for x, y in zip(a_closes[-n:], b_closes[-n:]) if y]
    return ratio or None


def _test_pair(leader_series: list[float], follower_series: list[float]) -> dict | None:
    n = min(len(leader_series), len(follower_series))
    leader_ret = _returns(leader_series[-n:])
    follower_ret = _returns(follower_series[-n:])
    m = min(len(leader_ret), len(follower_ret))
    if m < _MIN_RETURNS:
        return None
    data = np.column_stack([follower_ret[-m:], leader_ret[-m:]])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            results = grangercausalitytests(data, maxlag=_MAX_LAG)
    except Exception:
        return None
    best_lag, best_p = None, 1.0
    for lag in range(1, _MAX_LAG + 1):
        p = results[lag][0]["ssr_ftest"][1]
        if p < best_p:
            best_p, best_lag = p, lag
    if best_lag is None:
        return None
    return {
        "lag_days": best_lag,
        "p_value": round(float(best_p), 4),
        "significant": bool(best_p < _ALPHA),
        "sample_size": m,
    }


def compute_lead_lag() -> list[dict]:
    """[{"name", "label", "lag_days", "p_value", "significant", "sample_size"}, ...]
    for whichever curated pairs had enough data. Never fabricates a result
    for a pair with insufficient history -- silently skips it instead."""
    out = []
    for pair in _PAIRS:
        leader_series = _leader_series(pair["leader"])
        follower_series = _closes(pair["follower"])
        if leader_series is None or follower_series is None:
            continue
        result = _test_pair(leader_series, follower_series)
        if result is None:
            continue
        out.append({"name": pair["name"], "label": pair["label"], **result})
    return out


def get_lead_lag(force: bool = False) -> list[dict]:
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_lead_lag()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"] or []
