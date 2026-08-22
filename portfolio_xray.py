"""Portfolio X-Ray (FSI L4) -- factor-level risk decomposition: market,
rates, dollar, oil, vol, and cross-sectional momentum exposures per
holding, with concentration/crowding flags and a Scenario Lab hedge hook.
Deepens portfolio_risk.py (VaR/beta/drawdown/Sharpe) rather than
duplicating it -- this module answers "why" the portfolio has the risk
portfolio_risk.py already measures, one layer down.

Ships 6 factors this round: MARKET (SPY), RATES (10Y Treasury yield
changes, inverted -- a positive RATES beta means a position benefits
when yields FALL, i.e. duration-like/growth-style exposure), DOLLAR
(FRED DTWEXBGS broad dollar index), OIL (WTI, CL=F), VOL (^VIX changes),
and MOMENTUM (long top-quintile / short bottom-quintile 6-month return
within a curated 25-name universe). The playbook's other two named
factors are deliberately deferred, not fabricated:
  - SENTIMENT would need a >120-day daily sentiment aggregate, and
    news_items is capped at 72h retention -- a request-time query
    genuinely cannot grow a baseline out of a fixed-retention table
    (same structural blocker already documented for volume_anomaly.py
    /#149; this isn't a bootstrap-in-progress, it needs its own
    persisted daily-aggregate table first).
  - CROWDING (short-volume + signal-density composite) needs reliable
    per-symbol short-volume history for arbitrary holdings, which
    finra_short_volume.py doesn't guarantee.
"Regime-aware hedge examples" (playbook step 4) is also skipped --
regime_engine doesn't exist (#103, blocked on user risk:high go/no-go),
same documented omission divergence_radar.py already made for the
identical reason.

Request-time computation with a 12h result cache (same shape as
portfolio_risk.py/stress_test.py) rather than a new persisted
factor_returns table + scheduled job -- consistent with how every other
portfolio-analytics feature in this codebase already works, and avoids
a second job-scheduling + backfill surface for what is, at Fred's
current data volume (<=~15 positions x 120 days x 6 factors), a cheap
live computation once daily closes are warm in portfolio_risk.py's own
12h cache.

Pure Python by design, same MISSION.md Principle #5/#7 reasoning as
portfolio_risk.py: OLS solved via Gauss-Jordan elimination on tiny
(<=6-factor) normal-equation matrices, no numpy/pandas -- keeps the
Pi-lite deployment budget intact and every number explainable.
"""
import math
import time
from datetime import datetime

from portfolio_risk import _daily_closes, _returns_on_dates, _mean, _stdev
from dollar_index_client import _fetch_series as _dollar_index_fetch
from divergence_radar import _fred_series, _DGS10_URL

FACTOR_WINDOW_DAYS = 120
MOMENTUM_LOOKBACK_DAYS = 126  # ~6 trading months
MIN_DAYS = 60                  # same floor as portfolio_risk.py -- below this,
                                # refuse to print numbers rather than fake confidence
MIN_MOMENTUM_BREADTH = 10      # need this many priced universe names for a meaningful quintile split
COLLINEARITY_R = 0.85
CONCENTRATION_PCT = 20.0
CROWDING_LOAD = 0.6

VOL_TICKER = "^VIX"
OIL_TICKER = "CL=F"
MARKET_TICKER = "SPY"

# Curated cross-sectional momentum universe: one liquid US large-cap per
# major graph_engine.SECTORS bucket. ASX and crypto names deliberately
# excluded -- their trading calendars don't align with the business-day-
# only macro series below, which would silently corrupt the common-date
# intersection. Kept deliberately small (12, not graph_engine.SECTORS'
# full 100+): a cold-cache momentum build already means MARKET+OIL+VOL+
# every position + this whole universe as back-to-back first-time
# _daily_closes calls, and a live burst that size was confirmed live
# (2026-07-25) to trip Yahoo's real per-IP rate limit outright, not just
# this app's own internal "pausing YF requests" flag -- a 25-name
# universe made the feature nearly unable to ever complete its own cold
# start. 12 names + MOMENTUM_FETCH_STAGGER_S below is the fix, not just
# a smaller number picked arbitrarily.
MOMENTUM_UNIVERSE = [
    "NVDA", "MSFT", "META", "PLTR", "TSLA", "AAPL",
    "JPM", "LMT", "XOM", "MRNA", "V", "UBER",
]

# Extra stagger before each *new* (uncached) momentum-universe symbol, on
# top of portfolio_risk._daily_closes's own internal 0.5s-per-period-
# attempt sleep -- the two together are what actually keeps a cold-start
# burst under Yahoo's real per-IP limit, confirmed the 0.5s-only version
# was not enough on its own.
MOMENTUM_FETCH_STAGGER_S = 0.8

FACTORS = ("MARKET", "RATES", "DOLLAR", "OIL", "VOL", "MOMENTUM")

# Suggested scenario_engine.SHOCK_VOCABULARY key per dominant factor, for
# the "stress my top factor" one-tap Scenario Lab hook (playbook step 5).
# MOMENTUM has no scenario_engine analogue -- left unmapped rather than
# forced onto an unrelated shock.
SCENARIO_FACTOR_MAP = {
    "MARKET": "equities",
    "RATES": "yield_10y",
    "DOLLAR": "dxy",
    "OIL": "wti",
    "VOL": "vix",
}

_XRAY_TTL = 12 * 3600
_xray_cache: dict[tuple, tuple[float, dict]] = {}


def _level_diff(dates: list[str], series: dict[str, float]) -> list[float]:
    """Raw level difference (not a % return) aligned the same way
    portfolio_risk._returns_on_dates aligns pct returns: len(dates)-1 points."""
    out = []
    prev = None
    for d in dates:
        v = series[d]
        if prev is not None:
            out.append(v - prev)
        prev = v
    return out


def _pearson(a: list[float], b: list[float]) -> float:
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return 0.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


def _covariance(a: list[float], b: list[float]) -> float:
    if len(a) < 2:
        return 0.0
    ma, mb = _mean(a), _mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)


def _drop_collinear(names: tuple[str, ...], factor_returns: dict[str, list[float]]) -> tuple[list[str], list[dict]]:
    """Pairwise |corr| > COLLINEARITY_R among factor columns -> drop the
    later-listed factor of each colliding pair. Returns (kept, dropped_notes)."""
    kept = list(names)
    dropped = []
    i = 0
    while i < len(kept):
        j = i + 1
        while j < len(kept):
            r = _pearson(factor_returns[kept[i]], factor_returns[kept[j]])
            if abs(r) > COLLINEARITY_R:
                dropped.append({"dropped": kept[j], "kept_instead": kept[i], "corr": round(r, 2)})
                kept.pop(j)
            else:
                j += 1
        i += 1
    return kept, dropped


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss-Jordan elimination with partial pivoting. None on a singular
    matrix (shouldn't happen with real factor data past the collinearity
    guard, but fail honestly rather than crash or fabricate a solution)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-12:
            return None
        M[col], M[pivot_row] = M[pivot_row], M[col]
        pivot = M[col][col]
        M[col] = [v / pivot for v in M[col]]
        for r in range(n):
            if r != col:
                factor = M[r][col]
                M[r] = [M[r][c] - factor * M[col][c] for c in range(n + 1)]
    return [M[r][n] for r in range(n)]


def _ols(y: list[float], X: list[list[float]]) -> tuple[list[float], float, float]:
    """Multiple OLS with intercept, no numpy. X: rows aligned to y, no
    intercept column (added internally). Returns (betas per X column,
    alpha/intercept, r_squared)."""
    n = len(y)
    k = len(X[0]) if X and X[0] else 0
    if k == 0 or n <= k:
        return [0.0] * k, 0.0, 0.0
    design = [[1.0] + row for row in X]
    p = k + 1
    DtD = [[sum(design[r][a] * design[r][b] for r in range(n)) for b in range(p)] for a in range(p)]
    Dty = [sum(design[r][a] * y[r] for r in range(n)) for a in range(p)]
    coeffs = _solve_linear_system(DtD, Dty)
    if coeffs is None:
        return [0.0] * k, 0.0, 0.0
    alpha, betas = coeffs[0], coeffs[1:]
    y_mean = _mean(y)
    ss_tot = sum((v - y_mean) ** 2 for v in y)
    fitted = [alpha + sum(betas[j] * X[r][j] for j in range(k)) for r in range(n)]
    ss_res = sum((y[r] - fitted[r]) ** 2 for r in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return betas, alpha, max(0.0, min(1.0, r2))


def _momentum_basket(dates: list[str]) -> tuple[list[str] | None, list[str] | None, dict]:
    """Rank MOMENTUM_UNIVERSE by trailing MOMENTUM_LOOKBACK_DAYS return as
    of dates[-1], split into top/bottom quintile ONCE (not rebalanced
    daily within the fitting window -- a real simplification: proper
    daily rebalancing would need a full historical ranking timeline, not
    just point-in-time closes, and is left as a documented follow-up)."""
    scored = []
    universe_closes = {}
    for sym in MOMENTUM_UNIVERSE:
        time.sleep(MOMENTUM_FETCH_STAGGER_S)
        closes = _daily_closes(sym)
        if not closes:
            continue
        universe_closes[sym] = closes
        prior = sorted(d for d in closes if d <= dates[-1])
        if len(prior) < MOMENTUM_LOOKBACK_DAYS:
            continue
        window = prior[-MOMENTUM_LOOKBACK_DAYS:]
        if closes[window[0]] <= 0:
            continue
        scored.append((sym, closes[window[-1]] / closes[window[0]] - 1.0))
    if len(scored) < MIN_MOMENTUM_BREADTH:
        return None, None, universe_closes
    scored.sort(key=lambda x: x[1], reverse=True)
    q = max(1, len(scored) // 5)
    return [s for s, _ in scored[:q]], [s for s, _ in scored[-q:]], universe_closes


def _basket_returns(dates: list[str], symbols: list[str], universe_closes: dict) -> list[float] | None:
    rets = []
    for sym in symbols:
        closes = universe_closes.get(sym) or {}
        if all(d in closes for d in dates):
            rets.append(_returns_on_dates(closes, dates))
    if not rets:
        return None
    n = len(rets)
    return [sum(r[i] for r in rets) / n for i in range(len(dates) - 1)]


def _build_factor_returns(dates: list[str], market, dollar, oil, vol, rates) -> dict[str, list[float]] | None:
    top, bottom, universe_closes = _momentum_basket(dates)
    if not top or not bottom:
        return None
    top_ret = _basket_returns(dates, top, universe_closes)
    bot_ret = _basket_returns(dates, bottom, universe_closes)
    if top_ret is None or bot_ret is None:
        return None
    momentum = [t - b for t, b in zip(top_ret, bot_ret)]
    return {
        "MARKET": _returns_on_dates(market, dates),
        "RATES": [-x for x in _level_diff(dates, rates)],
        "DOLLAR": _returns_on_dates(dollar, dates),
        "OIL": _returns_on_dates(oil, dates),
        "VOL": _returns_on_dates(vol, dates),
        "MOMENTUM": momentum,
    }


def compute_xray(positions: list[dict], total_value: float | None = None) -> dict:
    """positions: [{symbol, value, ...}] as produced by calculate_portfolio_value.
    Returns real numbers or an honest status string -- never a placeholder
    (MISSION.md Principle #7), same convention as portfolio_risk.compute_portfolio_risk."""
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return {"status": "no_positions"}

    pos_histories = {p["symbol"]: _daily_closes(p["symbol"]) for p in positions}
    market = _daily_closes(MARKET_TICKER)
    dollar = _dollar_index_fetch()
    oil = _daily_closes(OIL_TICKER)
    vol = _daily_closes(VOL_TICKER)
    rates = _fred_series(_DGS10_URL)

    if not market or not dollar or not oil or not vol or not rates or all(not c for c in pos_histories.values()):
        return {"status": "data_unavailable"}

    common = set(market) & set(dollar) & set(oil) & set(vol) & set(rates)
    covered_positions = [p for p in positions if pos_histories.get(p["symbol"])]
    for p in covered_positions:
        common &= set(pos_histories[p["symbol"]])
    dates = sorted(common)[-(FACTOR_WINDOW_DAYS + 1):]
    if len(dates) < MIN_DAYS:
        return {"status": "insufficient_history", "days": len(dates), "min_days": MIN_DAYS}

    factor_returns = _build_factor_returns(dates, market, dollar, oil, vol, rates)
    if factor_returns is None:
        return {"status": "data_unavailable"}

    kept, dropped_collinear = _drop_collinear(FACTORS, factor_returns)
    n_points = len(dates) - 1

    total = total_value or sum(p["value"] for p in positions)
    weights = {p["symbol"]: p["value"] / total for p in positions}

    positions_out = {}
    predicted_by_symbol: dict[str, list[float]] = {}
    for p in positions:
        sym = p["symbol"]
        closes = pos_histories.get(sym)
        if not closes or not all(d in closes for d in dates):
            positions_out[sym] = {"status": "data_unavailable"}
            continue
        y = _returns_on_dates(closes, dates)
        X = [[factor_returns[f][i] for f in kept] for i in range(n_points)]
        betas, alpha, r2 = _ols(y, X)
        beta_map = dict(zip(kept, [round(b, 3) for b in betas]))
        positions_out[sym] = {
            "status": "ok",
            "weight_pct": round(weights[sym] * 100, 2),
            "betas": beta_map,
            "alpha": round(alpha, 5),
            "r_squared": round(r2, 3),
            "idiosyncratic": r2 < 0.15,
        }
        predicted_by_symbol[sym] = [alpha + sum(betas[j] * X[t][j] for j in range(len(kept))) for t in range(n_points)]

    ok_symbols = [s for s, v in positions_out.items() if v["status"] == "ok"]
    coverage_pct = round(100 * sum(weights[s] for s in ok_symbols), 1) if ok_symbols else 0.0

    if not ok_symbols:
        return {
            "status": "ok",
            "as_of": datetime.utcnow().isoformat() + "Z",
            "days": n_points,
            "coverage_pct": 0.0,
            "positions": positions_out,
            "portfolio_exposure": {},
            "variance_contribution_pct": {},
            "concentration_flags": [],
            "crowding_flags": [],
            "effective_n": None,
            "dropped_collinear": dropped_collinear,
            "dominant_factor": None,
            "scenario_hook": None,
        }

    portfolio_exposure = {
        f: round(sum(weights[s] * positions_out[s]["betas"].get(f, 0.0) for s in ok_symbols), 3)
        for f in kept
    }

    port_pred = [sum(weights[s] * predicted_by_symbol[s][t] for s in ok_symbols) for t in range(n_points)]
    total_factor_variance = _covariance(port_pred, port_pred)

    # Factor-level decomposition: contrib_f = b_f * (Sigma . b)_f, sums
    # exactly to b'Sigma b = total_factor_variance by construction.
    variance_contribution_pct = {}
    if total_factor_variance > 0:
        sigma_b = {
            f: sum(portfolio_exposure[g] * _covariance(factor_returns[f], factor_returns[g]) for g in kept)
            for f in kept
        }
        for f in kept:
            contrib = portfolio_exposure[f] * sigma_b[f]
            variance_contribution_pct[f] = round(100 * contrib / total_factor_variance, 1)

    # Position-level decomposition (Euler on positions instead of factors):
    # pos_contrib_s = weight_s * Cov(pred_s, port_pred); sums exactly to
    # total_factor_variance by the same identity.
    concentration_flags = []
    effective_n = None
    if total_factor_variance > 0:
        pos_shares = {}
        for s in ok_symbols:
            contrib = weights[s] * _covariance(predicted_by_symbol[s], port_pred)
            pos_shares[s] = contrib / total_factor_variance
        for s, share in pos_shares.items():
            if share * 100 > CONCENTRATION_PCT:
                concentration_flags.append({
                    "symbol": s, "factor_risk_share_pct": round(share * 100, 1),
                })
        # Effective-N (Herfindahl) on non-negative risk-contribution shares --
        # a position that's actually diversifying (negative share) doesn't
        # count as a "bet" for this purpose, documented convention.
        clipped = [max(0.0, v) for v in pos_shares.values()]
        denom = sum(v * v for v in clipped)
        effective_n = round(1.0 / denom, 2) if denom > 0 else None

    crowding_flags = []
    for f in kept:
        loaded = [s for s in ok_symbols if positions_out[s]["betas"].get(f, 0.0) > CROWDING_LOAD]
        if len(loaded) >= 2:
            crowding_flags.append({"factor": f, "symbols": loaded})

    dominant_factor = None
    if variance_contribution_pct:
        dominant_factor = max(variance_contribution_pct, key=lambda f: abs(variance_contribution_pct[f]))

    result = {
        "status": "ok",
        "as_of": datetime.utcnow().isoformat() + "Z",
        "days": n_points,
        "coverage_pct": coverage_pct,
        "positions": positions_out,
        "portfolio_exposure": portfolio_exposure,
        "variance_contribution_pct": variance_contribution_pct,
        "concentration_flags": concentration_flags,
        "crowding_flags": crowding_flags,
        "effective_n": effective_n,
        "dropped_collinear": dropped_collinear,
        "dominant_factor": dominant_factor,
        "scenario_hook": SCENARIO_FACTOR_MAP.get(dominant_factor) if dominant_factor else None,
    }

    key = tuple(sorted((p["symbol"], round(p["value"], 2)) for p in positions))
    _xray_cache[key] = (time.time(), result)
    return result


def get_cached_xray(positions: list[dict]) -> dict | None:
    """Serve the last computed X-ray for these holdings without any network
    I/O -- chat context must never block on this. None until the Portfolio
    tab (or the API) has computed it once, same contract as
    portfolio_risk.get_cached_risk."""
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return None
    key = tuple(sorted((p["symbol"], round(p["value"], 2)) for p in positions))
    hit = _xray_cache.get(key)
    if hit and time.time() - hit[0] < _XRAY_TTL:
        return hit[1]
    return None


def format_xray_line(xray: dict | None) -> str:
    """One compact line for Fred's chat context block -- only fires when
    there's a real concentration or crowding flag worth surfacing."""
    if not xray or xray.get("status") != "ok":
        return ""
    parts = []
    if xray.get("dominant_factor"):
        pct = xray["variance_contribution_pct"].get(xray["dominant_factor"])
        parts.append(f"dominant factor {xray['dominant_factor']} ({pct:+.0f}% of factor risk)")
    for c in xray.get("concentration_flags", []):
        parts.append(f"{c['symbol']} is {c['factor_risk_share_pct']:.0f}% of factor risk (concentrated)")
    for c in xray.get("crowding_flags", []):
        parts.append(f"{c['factor']} crowded: {', '.join(c['symbols'])}")
    if not parts:
        return ""
    return "PORTFOLIO X-RAY: " + " | ".join(parts)
