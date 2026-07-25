"""Portfolio risk metrics — annualized volatility, Sharpe, Sortino, max
drawdown, historical-simulation VaR, and beta vs SPY, computed from daily
closes the app already knows how to fetch (market_data.fetch_history).

Pure Python by design: at ~252 daily points x a handful of positions the
math is trivial, and adding numpy/pandas would break the Pi-lite deployment
budget for no gain. Historical simulation for VaR (no distribution
assumption) keeps every number explainable — MISSION.md Principle #5/#7.
"""

import math
import time
from datetime import datetime, timedelta

import requests

from market_data import fetch_history, _HEADERS

BENCHMARK = "SPY"
TRADING_DAYS = 252
MIN_DAYS = 60           # below this, refuse to print numbers rather than fake confidence
VAR_CONFIDENCE = 0.95

# Daily closes barely move intraday for risk purposes; cache aggressively so
# a Portfolio-tab visit costs at most one history call per symbol per 12h.
_HISTORY_TTL = 12 * 3600
_history_cache: dict[str, tuple[float, dict[str, float]]] = {}

# Last computed risk per position-fingerprint. get_cached_risk() serves chat
# context from here without ever blocking on network.
_RISK_TTL = 12 * 3600
_risk_cache: dict[tuple, tuple[float, dict]] = {}


# Same ETF detection as market_data._fetch_nasdaq — Nasdaq's API 404s when
# the assetclass is wrong.
_NASDAQ_ETFS = ("SPY", "QQQ", "IWM", "GLD", "TLT")


def _nasdaq_daily_closes(symbol: str) -> dict[str, float]:
    """Fallback daily history from Nasdaq's public API (US stocks/ETFs only —
    no .AX, no crypto). Yahoo's 1y-range budget exhausts hours before its
    short-range one (observed live), and this app already talks to
    api.nasdaq.com for quotes, so it's the natural second source."""
    if symbol.endswith(".AX") or "-" in symbol:
        return {}
    assetclass = "etf" if symbol in _NASDAQ_ETFS else "stocks"
    today = datetime.utcnow().date()
    try:
        r = requests.get(
            f"https://api.nasdaq.com/api/quote/{symbol}/historical",
            params={
                "assetclass": assetclass,
                "limit": 260,
                "fromdate": (today - timedelta(days=366)).isoformat(),
                "todate": today.isoformat(),
            },
            headers=_HEADERS, timeout=15,
        )
        if r.status_code != 200:
            return {}
        rows = ((r.json().get("data") or {}).get("tradesTable") or {}).get("rows") or []
        closes = {}
        for row in rows:
            try:
                m, d, y = row["date"].split("/")
                closes[f"{y}-{m}-{d}"] = float(row["close"].replace("$", "").replace(",", ""))
            except (KeyError, ValueError, AttributeError):
                continue
        return closes
    except Exception:
        return {}


def _daily_closes(symbol: str) -> dict[str, float]:
    """date (YYYY-MM-DD) -> close, ~1y of daily bars."""
    now = time.time()
    hit = _history_cache.get(symbol)
    if hit and now - hit[0] < _HISTORY_TTL:
        return hit[1]
    # Stagger uncached fetches — 4+ back-to-back history calls is exactly the
    # burst pattern that trips Yahoo's per-host limit (observed live). Longer
    # ranges also have their own stricter budget (1y can 429 while 5d serves
    # 200), so degrade 1y → 6mo → 3mo, then fall back to Nasdaq entirely; the
    # result already reports how many days actually backed the numbers.
    for period in ("1y", "6mo", "3mo"):
        time.sleep(0.5)
        records = fetch_history(symbol, period=period, interval="1d")
        closes = {r["time"][:10]: r["close"] for r in records if r.get("close")}
        if closes:
            _history_cache[symbol] = (now, closes)
            return closes
    closes = _nasdaq_daily_closes(symbol)
    if closes:
        _history_cache[symbol] = (now, closes)
    return closes


def _returns_on_dates(closes: dict[str, float], dates: list[str]) -> list[float]:
    out = []
    prev = None
    for d in dates:
        c = closes[d]
        if prev is not None and prev > 0:
            out.append(c / prev - 1.0)
        prev = c
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _max_drawdown(returns: list[float]) -> float:
    """Worst peak-to-trough decline of the cumulative curve, as a negative fraction."""
    peak = 1.0
    curve = 1.0
    worst = 0.0
    for r in returns:
        curve *= 1.0 + r
        peak = max(peak, curve)
        worst = min(worst, curve / peak - 1.0)
    return worst


def _historical_var(returns: list[float], confidence: float = VAR_CONFIDENCE) -> float:
    """1-day VaR as a positive fraction: the loss at the (1-confidence) quantile."""
    ordered = sorted(returns)
    idx = max(0, min(len(ordered) - 1, int(math.floor((1.0 - confidence) * len(ordered)))))
    return max(0.0, -ordered[idx])


def _beta(port: list[float], bench: list[float]) -> float | None:
    if len(port) != len(bench) or len(port) < 2:
        return None
    mp, mb = _mean(port), _mean(bench)
    var_b = sum((b - mb) ** 2 for b in bench)
    if var_b == 0:
        return None
    cov = sum((p - mp) * (b - mb) for p, b in zip(port, bench))
    return cov / var_b


def kelly_fraction(returns: list[float]) -> dict | None:
    """Classic Kelly fraction f* = W - (1-W)/R, W = historical win rate,
    R = avg-win/avg-loss size ratio, both derived from the same per-position
    daily-return sample used for VaR/Sharpe above. Half-Kelly is the number
    worth acting on (full Kelly is well-known to be too aggressive for real
    capital) but both are returned — never hide the fuller number (Principle
    #7). Returns None below MIN_DAYS, or when the sample has no realized win
    or loss at all, rather than fabricate a sizing number off too few points.
    """
    if len(returns) < MIN_DAYS:
        return None
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    if not wins or not losses:
        return None
    win_rate = len(wins) / len(returns)
    avg_win = _mean(wins)
    avg_loss = abs(_mean(losses))
    if avg_loss == 0:
        return None
    ratio = avg_win / avg_loss
    full = win_rate - (1.0 - win_rate) / ratio
    return {
        "full_kelly_pct": round(full * 100, 2),
        "half_kelly_pct": round(full * 50, 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "win_loss_ratio": round(ratio, 2),
        "sample_size": len(returns),
    }


def compute_portfolio_risk(positions: list[dict], total_value: float | None = None) -> dict:
    """positions: [{symbol, value, ...}] as produced by calculate_portfolio_value.

    Returns real numbers or an honest {"status": "insufficient_history"} —
    never placeholder values (MISSION.md Principle #7).
    """
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return {"status": "no_positions"}

    histories = {p["symbol"]: _daily_closes(p["symbol"]) for p in positions}
    bench_closes = _daily_closes(BENCHMARK)

    # No data at all is a fetch problem (rate limit, outage), not short history —
    # saying "you have 0 days of history" to a holder of AAPL would be a lie.
    if not bench_closes or all(not c for c in histories.values()):
        return {"status": "data_unavailable"}

    # Portfolio returns only exist on dates where every holding has a close
    # (drops crypto weekends when stocks are held alongside — correct, not a bug:
    # a portfolio return on a day half the book didn't trade is fiction).
    common = set(bench_closes)
    for closes in histories.values():
        common &= set(closes)
    dates = sorted(common)
    if len(dates) < MIN_DAYS:
        return {
            "status": "insufficient_history",
            "days": len(dates),
            "min_days": MIN_DAYS,
        }

    total = total_value or sum(p["value"] for p in positions)
    weights = {p["symbol"]: p["value"] / total for p in positions}

    per_symbol = {sym: _returns_on_dates(histories[sym], dates) for sym in histories}
    port_returns = [
        sum(weights[sym] * per_symbol[sym][i] for sym in per_symbol)
        for i in range(len(dates) - 1)
    ]
    bench_returns = _returns_on_dates(bench_closes, dates)

    daily_mean = _mean(port_returns)
    daily_sd = _stdev(port_returns)
    downside = [r for r in port_returns if r < 0]
    downside_sd = _stdev(downside) if len(downside) >= 2 else 0.0

    ann_return = daily_mean * TRADING_DAYS
    ann_vol = daily_sd * math.sqrt(TRADING_DAYS)
    var_frac = _historical_var(port_returns)

    result = {
        "status": "ok",
        "as_of": datetime.utcnow().isoformat() + "Z",
        "days": len(port_returns),
        "annual_volatility_pct": round(ann_vol * 100, 2),
        # rf=0 by definition here and labeled as such in the UI — a wrong
        # hardcoded risk-free rate is worse than a stated simplification.
        "sharpe": round(ann_return / ann_vol, 2) if ann_vol > 0 else None,
        "sortino": round(ann_return / (downside_sd * math.sqrt(TRADING_DAYS)), 2)
        if downside_sd > 0 else None,
        "max_drawdown_pct": round(_max_drawdown(port_returns) * 100, 2),
        "var_95_1d_pct": round(var_frac * 100, 2),
        "var_95_1d_value": round(var_frac * total, 2),
        "beta_spy": (lambda b: round(b, 2) if b is not None else None)(
            _beta(port_returns, bench_returns)
        ),
        "benchmark": BENCHMARK,
        "positions": [
            {"symbol": sym, "kelly": kelly_fraction(per_symbol[sym])}
            for sym in per_symbol
        ],
    }

    key = tuple(sorted((p["symbol"], round(p["value"], 2)) for p in positions))
    _risk_cache[key] = (time.time(), result)
    return result


def get_cached_risk(positions: list[dict]) -> dict | None:
    """Serve the last computed risk for these holdings without any network
    I/O — chat context must never block on ~N history fetches. Returns None
    until the Portfolio tab (or the API) has computed it once."""
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return None
    key = tuple(sorted((p["symbol"], round(p["value"], 2)) for p in positions))
    hit = _risk_cache.get(key)
    if hit and time.time() - hit[0] < _RISK_TTL:
        return hit[1]
    return None


def format_risk_line(risk: dict | None) -> str:
    """One compact line for Fred's chat context block."""
    if not risk or risk.get("status") != "ok":
        return ""
    parts = [
        f"vol {risk['annual_volatility_pct']}%/yr",
        f"Sharpe {risk['sharpe']}" if risk.get("sharpe") is not None else None,
        f"maxDD {risk['max_drawdown_pct']}%",
        f"1d VaR(95%) ${risk['var_95_1d_value']:,.0f}",
        f"beta {risk['beta_spy']}" if risk.get("beta_spy") is not None else None,
    ]
    return "PORTFOLIO RISK ({}d): {}".format(risk["days"], " | ".join(p for p in parts if p))
