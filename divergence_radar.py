"""Divergence Radar (FSI L2) -- real-time detection of cross-asset
disagreements: named, explainable pairs of series that normally move
together (or apart) in a well-understood way, flagged when they stop.

Curated beats exhaustive (playbook's own framing): 6 pairs, each backed by
a feed this codebase already ingests for its own macro badge, reused here
rather than duplicated fetch logic wherever a raw historical series is
already exposed by that badge's private fetch function (same cross-module
reuse precedent as portfolio_risk._daily_closes). One leg (10Y yield) needs
its own FRED CSV fetch since yield_curve.py only exposes the computed 2s10s
spread from a live snapshot, not a raw historical series -- same free
fredgraph.csv pattern used by every other FRED-sourced badge in this repo.
finra_short_volume.py is per-symbol rather than a market-wide series, so it
doesn't fit a clean pair without picking an arbitrary symbol -- left out
rather than forced in, same "playbook's suggested list vs what's actually
cleanly reusable" honesty already established for Filing Intelligence and
Research Desk.

Every divergence alert states its historical base rate honestly, including
"insufficient history" (n too small to mean anything) -- this is the whole
point of the feature, not an edge case to hide.
"""
import statistics
import time
from datetime import datetime, timedelta

import requests

from portfolio_risk import _daily_closes
from credit_oas_spread import _fetch_series as _credit_oas_fetch, _HY_URL
from dollar_index_client import _fetch_series as _dollar_index_fetch
from memory_store import get_divergence_events, upsert_divergence_event

ROLLING_WINDOW = 60
TRIGGER_Z = 2.0
SUSTAIN_DAYS = 3
CONVERGED_Z = 1.0  # spread must fall back under this to count as resolved
STALE_DAYS = 5      # a leg whose latest data point is older than this is stale

_DGS10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
_fred_cache: dict[str, tuple[float, dict]] = {}
_FRED_TTL_S = 3600


def _fred_series(url: str) -> dict[str, float]:
    """date -> value, generic FRED fredgraph.csv fetch (same pattern as
    dollar_index_client.py/credit_oas_spread.py), cached separately from
    those modules' own caches since this needs the full series, not their
    trend-snapshot shape."""
    now = time.time()
    hit = _fred_cache.get(url)
    if hit and now - hit[0] < _FRED_TTL_S:
        return hit[1]
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        import csv, io
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    except Exception:
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date, raw = row[0], row[1]
        try:
            out[date] = float(raw)
        except ValueError:
            continue
    if out:
        _fred_cache[url] = (now, out)
    return out


def _hy_oas_series() -> dict[str, float]:
    series = _credit_oas_fetch(_HY_URL, "HY")
    return {d: v for d, v in series} if series else {}


def _dollar_index_series() -> dict[str, float]:
    series = _dollar_index_fetch()
    return dict(series) if series else {}


def _spy_realized_vol_series() -> dict[str, float]:
    """Trailing 20d annualized realized volatility of SPY, one value per
    trading day -- the "actual observed turbulence" leg for the VIX
    term-structure pair (VIX9D/VIX6M is the market's *implied* fear)."""
    closes = _daily_closes("SPY")
    dates = sorted(closes)
    if len(dates) < 22:
        return {}
    out = {}
    for i in range(21, len(dates)):
        window = dates[i - 20:i + 1]
        rets = [closes[window[j]] / closes[window[j - 1]] - 1.0 for j in range(1, len(window))]
        sd = statistics.pstdev(rets) if len(rets) >= 2 else 0.0
        out[dates[i]] = sd * (252 ** 0.5)
    return out


def _ratio_series(num: dict[str, float], den: dict[str, float]) -> dict[str, float]:
    return {d: num[d] / den[d] for d in num if d in den and den[d]}


# Each entry: two named legs (each a zero-arg callable returning a
# date->value series) plus the historically-expected relationship sign
# (+1 = normally move together, -1 = normally move opposite) and a
# human-readable rationale for what a divergence would mean.
PAIR_REGISTRY = {
    "credit_vs_equities": {
        "label": "Credit (HY OAS) vs Equities (SPY)",
        "leg_a": ("HY OAS (bps, higher=stress)", _hy_oas_series),
        "leg_b": ("SPY", lambda: _daily_closes("SPY")),
        "expected_sign": -1,
        "rationale": "Credit stress (widening HY OAS) normally accompanies equity "
                     "weakness. Divergence: spread widens while equities stay calm/rising, "
                     "or equities selloff while credit stays calm -- one market hasn't "
                     "caught up to the other yet.",
    },
    "breadth_vs_index": {
        "label": "Breadth (RSP) vs Index (SPY)",
        "leg_a": ("RSP", lambda: _daily_closes("RSP")),
        "leg_b": ("SPY", lambda: _daily_closes("SPY")),
        "expected_sign": 1,
        "rationale": "Equal-weight (RSP) and cap-weight (SPY) S&P 500 normally move "
                     "together. Divergence: index rising while breadth falls behind is "
                     "the classic narrow-leadership late-cycle warning.",
    },
    "copper_gold_vs_yields": {
        "label": "Copper/Gold vs 10Y Yield",
        "leg_a": ("CPER/GLD ratio", lambda: _ratio_series(_daily_closes("CPER"), _daily_closes("GLD"))),
        "leg_b": ("10Y Treasury yield", lambda: _fred_series(_DGS10_URL)),
        "expected_sign": 1,
        "rationale": "Both are growth/inflation-expectation proxies (commodity-market "
                     "and rates-market versions of the same view) and normally move "
                     "together. Divergence: the commodity market pricing a growth scare "
                     "while rates markets haven't repriced yet, or vice versa.",
    },
    "vix_term_vs_realized_vol": {
        "label": "VIX Term Structure vs Realized Vol",
        "leg_a": ("VIX9D/VIX6M ratio", lambda: _ratio_series(_daily_closes("^VIX9D"), _daily_closes("^VIX6M"))),
        "leg_b": ("SPY 20d realized vol", _spy_realized_vol_series),
        "expected_sign": 1,
        "rationale": "Options-implied near-term fear (VIX9D/VIX6M backwardation) "
                     "normally tracks actually-realized turbulence. Divergence: implied "
                     "fear spiking with no realized chop yet (pre-emptive hedging "
                     "demand), or realized chop with no term-structure repricing "
                     "(complacent pricing of ongoing moves).",
    },
    "dollar_vs_copper_gold": {
        "label": "Dollar Index vs Copper/Gold",
        "leg_a": ("DTWEXBGS (broad dollar index)", _dollar_index_series),
        "leg_b": ("CPER/GLD ratio", lambda: _ratio_series(_daily_closes("CPER"), _daily_closes("GLD"))),
        "expected_sign": -1,
        "rationale": "A strengthening broad dollar normally pressures commodity-priced "
                     "growth assets (inverse relationship). Divergence: both rising "
                     "together is unusual and suggests a common driver other than the "
                     "textbook dollar-commodity channel (e.g. a broad reflationary shock).",
    },
    "skew_vs_vix": {
        "label": "SKEW vs VIX",
        "leg_a": ("^SKEW", lambda: _daily_closes("^SKEW")),
        "leg_b": ("^VIX", lambda: _daily_closes("^VIX")),
        "expected_sign": 1,
        "rationale": "Broad fear (VIX) and tail-risk pricing (SKEW) are mildly "
                     "positively correlated over time. The well-known interesting case "
                     "is exactly the divergence: low VIX (complacent broad market) with "
                     "elevated SKEW (rising crash-insurance demand) has historically "
                     "preceded sharp drawdowns.",
    },
}


def _rolling_zscore(dated_values: dict[str, float], window: int = ROLLING_WINDOW) -> dict[str, float]:
    """date -> z-score of that day's value against the trailing `window`
    days BEFORE it (never including the day itself, so it isn't
    self-referential -- same convention as every _trend() helper in this
    codebase). Only emits a value once at least `window` prior days exist."""
    dates = sorted(dated_values)
    out = {}
    for i in range(window, len(dates)):
        baseline = [dated_values[dates[j]] for j in range(i - window, i)]
        mean = statistics.fmean(baseline)
        sd = statistics.pstdev(baseline)
        if sd == 0:
            continue
        out[dates[i]] = (dated_values[dates[i]] - mean) / sd
    return out


def compute_pair_spread(pair_key: str) -> dict | None:
    """Full aligned daily spread series for one pair, or None if either leg
    has too little history. `stale` is True when the leg's own most recent
    data point is more than STALE_DAYS old (feed degraded, not necessarily
    down) -- callers should show/flag this pair but not trust a fresh alert
    on it."""
    pair = PAIR_REGISTRY[pair_key]
    _, fetch_a = pair["leg_a"]
    _, fetch_b = pair["leg_b"]
    series_a, series_b = fetch_a(), fetch_b()
    if not series_a or not series_b:
        return None

    z_a, z_b = _rolling_zscore(series_a), _rolling_zscore(series_b)
    common = sorted(set(z_a) & set(z_b))
    if len(common) < SUSTAIN_DAYS:
        return None

    sign = pair["expected_sign"]
    spread = {d: z_a[d] - sign * z_b[d] for d in common}

    latest_raw_date = max(max(series_a), max(series_b))
    stale = (datetime.utcnow().date() - datetime.strptime(latest_raw_date, "%Y-%m-%d").date()).days > STALE_DAYS

    return {
        "spread": spread,
        "z_a": {d: z_a[d] for d in common}, "z_b": {d: z_b[d] for d in common},
        "stale": stale,
    }


def _days_between(d1: str, d2: str) -> int:
    return (datetime.strptime(d2, "%Y-%m-%d").date() - datetime.strptime(d1, "%Y-%m-%d").date()).days


def detect_events(pair_key: str) -> list[dict]:
    """Walks the full available spread history for one pair and returns
    every episode where |spread| >= TRIGGER_Z sustained SUSTAIN_DAYS
    consecutive days (no single-day noise). `started_at` is the FIRST day
    of that sustained streak, not the day it was confirmed -- an episode is
    honestly reported as starting when the divergence actually began.
    Resolution: spread falling back under CONVERGED_Z. `resolution_type` is
    "converged" if the spread never exceeded its initial trigger magnitude
    by a meaningful margin before resolving, "broke_further" if it did (got
    worse before it got better). The last entry has resolved_at=None if the
    episode is still active as of the latest available data."""
    result = compute_pair_spread(pair_key)
    if not result:
        return []
    return detect_events_from_spread(pair_key, result["spread"], result["z_a"], result["z_b"])


def detect_events_from_spread(pair_key: str, spread: dict[str, float],
                               z_a: dict[str, float], z_b: dict[str, float]) -> list[dict]:
    """Pure state-machine core of detect_events, split out so it's testable
    against a hand-built synthetic spread series without touching any live
    data fetch."""
    dates = sorted(spread)

    events: list[dict] = []
    streak_start = None
    streak_start_z = None
    streak_peak_z = None
    streak_peak_date = None
    streak_len = 0
    active: dict | None = None

    for d in dates:
        z = spread[d]
        if abs(z) >= TRIGGER_Z:
            if streak_len == 0:
                streak_start = d
                streak_start_z = z
                streak_peak_z = z
                streak_peak_date = d
            elif abs(z) > abs(streak_peak_z):
                streak_peak_z = z
                streak_peak_date = d
            streak_len += 1
        else:
            streak_len = 0
            streak_start = streak_start_z = streak_peak_z = streak_peak_date = None

        if active is None and streak_len >= SUSTAIN_DAYS:
            # initial_trigger_z is the value AT started_at (when the
            # divergence actually began), not the confirmation day's value
            # (SUSTAIN_DAYS later); peak_z/peak_date are seeded from the
            # running streak peak (tracked from day 1 of the streak), not
            # just the confirmation day -- otherwise a peak that occurred
            # during the first SUSTAIN_DAYS-1 days (before confirmation)
            # would be missed entirely. Both caught by fixture verification.
            active = {
                "pair": pair_key, "started_at": streak_start,
                "direction": "positive" if streak_start_z > 0 else "negative",
                "initial_trigger_z": streak_start_z,
                "peak_z": streak_peak_z, "peak_date": streak_peak_date,
                "z_a_at_start": z_a[streak_start], "z_b_at_start": z_b[streak_start],
            }
        elif active is not None:
            if abs(z) > abs(active["peak_z"]):
                active["peak_z"] = z
                active["peak_date"] = d
            if abs(z) < CONVERGED_Z:
                move_a = abs(z_a[d] - active["z_a_at_start"])
                move_b = abs(z_b[d] - active["z_b_at_start"])
                resolved_by = "a" if move_a >= move_b else "b"
                broke_further = abs(active["peak_z"]) > abs(active["initial_trigger_z"]) + 0.25
                events.append({
                    **{k: v for k, v in active.items() if not k.startswith("z_")},
                    "resolved_at": d,
                    "resolution_type": "broke_further" if broke_further else "converged",
                    "resolved_by": resolved_by,
                    "days_active": _days_between(active["started_at"], d),
                })
                active = None
                streak_len = 0
                streak_start = None

    if active is not None:
        events.append({
            **{k: v for k, v in active.items() if not k.startswith("z_")},
            "resolved_at": None, "resolution_type": None, "resolved_by": None,
            "days_active": _days_between(active["started_at"], dates[-1]),
        })

    return events


def historical_resolution_stats(pair_key: str) -> dict:
    """From every RESOLVED past event for this pair: sample size, how many
    resolved via each leg, and median days to resolve. Returns n=0 honestly
    rather than fabricating a rate from too little data -- "n=4" is a valid
    and important answer per the playbook's own hard constraint."""
    events = [e for e in detect_events(pair_key) if e["resolved_at"] is not None]
    n = len(events)
    if n == 0:
        return {"n": 0, "median_days_to_resolve": None, "resolved_by_a": 0, "resolved_by_b": 0}
    days = sorted(e["days_active"] for e in events)
    median = days[len(days) // 2] if n % 2 else (days[n // 2 - 1] + days[n // 2]) / 2
    return {
        "n": n,
        "median_days_to_resolve": median,
        "resolved_by_a": sum(1 for e in events if e["resolved_by"] == "a"),
        "resolved_by_b": sum(1 for e in events if e["resolved_by"] == "b"),
        "broke_further_count": sum(1 for e in events if e["resolution_type"] == "broke_further"),
    }


def sync_pair(pair_key: str) -> dict:
    """Reconciles this pair's freshly-detected events against what's
    persisted in divergence_events (a plain UPSERT keyed on (pair,
    started_at) -- an event's own started_at/resolved_at IS its state, so
    updating a still-open row in place as it resolves is the correct model
    here, unlike counterfactual_pnl's insert-only history-of-a-metric
    concern). Returns {"triggered": [...], "resolved": [...]} -- only
    events whose DB state actually just changed, for the caller to alert
    on (never re-alerts on an event that was already known)."""
    fresh = detect_events(pair_key)
    existing = {e["started_at"]: e for e in get_divergence_events(pair_key)}

    triggered, resolved = [], []
    for e in fresh:
        prior = existing.get(e["started_at"])
        if prior is None:
            triggered.append(e)
        elif prior.get("resolved_at") is None and e["resolved_at"] is not None:
            resolved.append(e)
        upsert_divergence_event(**e)

    return {"triggered": triggered, "resolved": resolved}


def run_daily_divergence_scan() -> dict:
    """Scheduled job entry point: syncs every pair, returns everything
    newly triggered/resolved this run plus each pair's current stale flag
    (degrade-per-pair, per the hard constraint -- one dead feed doesn't
    take down the whole radar)."""
    all_triggered, all_resolved, stale_pairs = [], [], []
    for pair_key in PAIR_REGISTRY:
        try:
            spread_result = compute_pair_spread(pair_key)
            if spread_result is None:
                stale_pairs.append(pair_key)
                continue
            if spread_result["stale"]:
                stale_pairs.append(pair_key)
            sync_result = sync_pair(pair_key)
            all_triggered.extend(sync_result["triggered"])
            all_resolved.extend(sync_result["resolved"])
        except Exception as e:
            print(f"[DivergenceRadar] {pair_key} error: {e}")
            stale_pairs.append(pair_key)
    return {"triggered": all_triggered, "resolved": all_resolved, "stale_pairs": stale_pairs}
