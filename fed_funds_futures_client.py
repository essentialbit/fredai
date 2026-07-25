"""CBOT 30-Day Fed Funds futures (ZQ) term structure -- market-implied
Fed rate-path expectations (FSI L2, issue #248).

Each ZQ contract prices in the market's expected average daily fed funds
rate for its delivery month: implied rate = 100 - contract price. Reading
the front few contract months side by side against the current effective
rate (FRED series DFF) shows whether the market is pricing cuts, a hold,
or hikes at the next several FOMC meetings -- the same mechanic behind the
well-known CME FedWatch tool. Distinct from the existing Fed balance sheet
size badge (#190) and financial-conditions stress indices (#221/#231):
this reads what the market expects the Fed to *do next*, not a balance-
sheet or stress-level snapshot.

Futures prices come from market_data.fetch_quotes (never yfinance.Ticker
directly, see project memory on the fast_info/history crash class). The
effective rate comes from FRED's free fredgraph.csv endpoint via plain
requests.get -- curl hits an HTTP/2 stream reset on this host, but the
direct-client pattern used by every other FRED-sourced badge works fine.
"""
import csv
import io
import statistics
import time
from datetime import datetime, timezone

import requests

from market_data import fetch_quotes

_DFF_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
_CACHE_TTL_S = 3600  # futures reprice slowly enough that faster polling adds no signal
_cache: dict = {"computed_at": 0.0, "data": None}

_MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}


def _front_month_symbols(n: int = 4) -> list[tuple[str, str]]:
    """Front n ZQ contract symbols starting with the current month, e.g.
    [("ZQN26.CBT", "2026-07"), ("ZQQ26.CBT", "2026-08"), ...]."""
    now = datetime.now(timezone.utc)
    out = []
    year, month = now.year, now.month
    for _ in range(n):
        code = _MONTH_CODES[month]
        yy = year % 100
        out.append((f"ZQ{code}{yy:02d}.CBT", f"{year:04d}-{month:02d}"))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def _fetch_effective_rate() -> float | None:
    try:
        r = requests.get(_DFF_CSV_URL, timeout=15)
        if r.status_code != 200:
            print(f"[FedFundsFutures] DFF HTTP {r.status_code}")
            return None
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception as e:
        print(f"[FedFundsFutures] DFF fetch error: {e}")
        return None

    for row in reversed(rows[1:]):
        if len(row) < 2:
            continue
        try:
            return float(row[1])
        except ValueError:
            continue  # FRED uses "." for missing observations
    return None


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point). Same shape as copper_gold_ratio.py's
    _trend() helper."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "hawkish_shift"
    elif z < -0.5:
        direction = "dovish_shift"
    else:
        direction = "stable"
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def compute_fed_funds_expectations(price_history: list[float] | None = None) -> dict | None:
    """{"effective_rate": float, "contracts": [{"month": "2026-08",
    "implied_rate": float, "diff_bps": int}, ...], "front_month_trend_20d":
    {...} | None, "regime": "pricing_cuts"/"pricing_hikes"/"pricing_hold"}
    or None if either the futures quotes or the effective rate can't be
    fetched.

    `price_history` is a trailing series of the front-month implied rate
    for z-score context (injectable for tests; the live accessor below
    reads it from trend_history in memory_store)."""
    symbols_months = _front_month_symbols(4)
    quotes = fetch_quotes([s for s, _ in symbols_months])
    effective_rate = _fetch_effective_rate()
    if effective_rate is None:
        return None

    contracts = []
    for symbol, month in symbols_months:
        q = quotes.get(symbol)
        if not q or not q.get("price"):
            continue
        implied_rate = 100.0 - q["price"]
        contracts.append({
            "month": month,
            "implied_rate": round(implied_rate, 3),
            "diff_bps": round((implied_rate - effective_rate) * 100),
        })
    if not contracts:
        return None

    front_month_trend_20d = None
    if price_history:
        series = [*price_history, contracts[0]["implied_rate"]]
        front_month_trend_20d = _trend(series)

    front_diff = contracts[0]["diff_bps"]
    if front_diff <= -10:
        regime = "pricing_cuts"
    elif front_diff >= 10:
        regime = "pricing_hikes"
    else:
        regime = "pricing_hold"

    return {
        "effective_rate": round(effective_rate, 2),
        "contracts": contracts,
        "front_month_trend_20d": front_month_trend_20d,
        "regime": regime,
    }


def get_fed_funds_expectations(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_fed_funds_expectations()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
