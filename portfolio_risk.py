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


def compute_portfolio_benchmark(
    positions: list[dict], total_value: float | None = None,
    benchmarks: tuple[str, ...] = ("SPY", "QQQ"),
) -> dict:
    """Actual-holdings equity curve vs SPY/QQQ buy-and-hold, rebased to the
    same start value (reasoning matches counterfactual_pnl._benchmark_curve,
    reimplemented here because that module simulates a signal-follower with
    its own capital pool, not the user's real (symbol, shares) positions).

    SIMPLIFICATION (must stay visible in the UI, not just here): this app
    has no historical position-change ledger, so every historical date is
    valued at CURRENT share counts x that date's close, not the share count
    actually held on that date. Honest for buy-and-hold-since-first-position
    users, overstates history for anyone who has since traded size.

    Same four-status contract as compute_portfolio_risk — never fakes a
    number below MIN_DAYS or when a fetch fails outright.
    """
    positions = [p for p in positions if (p.get("value") or 0) > 0]
    if not positions:
        return {"status": "no_positions"}

    shares = {p["symbol"]: float(p.get("shares") or 0) for p in positions}
    histories = {sym: _daily_closes(sym) for sym in shares}
    bench_closes = {b: _daily_closes(b) for b in benchmarks}

    if all(not c for c in histories.values()) or all(not c for c in bench_closes.values()):
        return {"status": "data_unavailable"}

    common = None
    for closes in histories.values():
        common = set(closes) if common is None else (common & set(closes))
    for closes in bench_closes.values():
        common &= set(closes)
    dates = sorted(common) if common else []
    if len(dates) < MIN_DAYS:
        return {
            "status": "insufficient_history",
            "days": len(dates),
            "min_days": MIN_DAYS,
        }

    portfolio_curve = [
        {"date": d, "value": round(sum(shares[sym] * histories[sym][d] for sym in shares), 2)}
        for d in dates
    ]
    start_value = portfolio_curve[0]["value"]

    result_benchmarks = {}
    for b in benchmarks:
        closes = bench_closes[b]
        base = closes[dates[0]]
        curve = [
            {"date": d, "value": round(start_value * closes[d] / base, 2) if base else 0.0}
            for d in dates
        ]
        end, start = closes[dates[-1]], closes[dates[0]]
        return_pct = round((end / start - 1.0) * 100, 2) if start else None
        result_benchmarks[b] = {"return_pct": return_pct, "curve": curve}

    port_start, port_end = portfolio_curve[0]["value"], portfolio_curve[-1]["value"]
    portfolio_return_pct = round((port_end / port_start - 1.0) * 100, 2) if port_start else None

    return {
        "status": "ok",
        "as_of": datetime.utcnow().isoformat() + "Z",
        "days": len(dates),
        "start_date": dates[0],
        "end_date": dates[-1],
        "portfolio_return_pct": portfolio_return_pct,
        "portfolio_curve": portfolio_curve,
        "benchmarks": result_benchmarks,
    }


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


def _is_long_term(acquired_date: str, as_of_date: str) -> bool:
    """Shared term-classification rule for both realized and unrealized gain
    math, so the two paths can never drift apart. Long-term when the holding
    period exceeds 365 days -- (as_of_or_disposal_date - acquired_date).days
    > 365, so exactly 365 days is still short-term. Real calendar-date
    subtraction (both inputs are the YYYY-MM-DD strings tax_lots/disposals
    already store), never a rounded 12-months/1-year approximation."""
    acquired = datetime.strptime(acquired_date, "%Y-%m-%d").date()
    as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    return (as_of - acquired).days > 365


def compute_unrealized_gain(lots: list[dict], prices: dict[str, float], as_of_date: str | None = None) -> dict:
    """Pure function: lots is memory_store.get_lots()'s shape (open tax_lots
    rows), prices is a pre-fetched {symbol: current price} map -- matching
    this file's existing convention (compute_portfolio_risk etc.) of taking
    already-fetched data rather than hitting the network/DB itself.

    Per-lot gain = shares * price - cost_basis (cost_basis is the lot's
    total dollar cost, not per-share, matching tax_lots' own convention). A
    lot whose symbol has no entry in `prices` is skipped from both the
    per-lot list and the totals -- no price to mark it against, so silently
    inventing a zero would misstate the total more than omitting it.
    `as_of_date` defaults to today (YYYY-MM-DD) but is overridable so the
    365-day boundary is deterministically testable. An empty lot list
    returns a zero/empty result, never an error.
    """
    as_of = as_of_date or datetime.utcnow().strftime("%Y-%m-%d")
    per_lot = []
    lt_gain = st_gain = 0.0
    for lot in lots:
        price = prices.get(lot["symbol"])
        if price is None:
            continue
        gain = lot["shares"] * price - lot["cost_basis"]
        term = "long_term" if _is_long_term(lot["acquired_date"], as_of) else "short_term"
        per_lot.append({
            "lot_id": lot["id"],
            "symbol": lot["symbol"],
            "shares": lot["shares"],
            "cost_basis": lot["cost_basis"],
            "market_value": round(lot["shares"] * price, 2),
            "gain": round(gain, 2),
            "term": term,
            "acquired_date": lot["acquired_date"],
        })
        if term == "long_term":
            lt_gain += gain
        else:
            st_gain += gain
    return {
        "as_of": as_of,
        "lots": per_lot,
        "long_term_gain": round(lt_gain, 2),
        "short_term_gain": round(st_gain, 2),
        "total_gain": round(lt_gain + st_gain, 2),
    }


def compute_realized_gain(disposals: list[dict]) -> dict:
    """Pure function: disposals is memory_store.get_disposals()'s shape --
    the sanctioned sole read path for realized-gain math. No code path here
    derives, infers, or backfills a disposal from portfolio share-count
    deltas, remove_lot history, or anything else.

    Each line item's cost_basis is already the dollar cost basis
    attributable to that line's shares_used (get_disposals' documented
    allocation semantic). Proceeds are allocated across a disposal's lines
    in proportion to shares_used, at that disposal's single per-share sale
    price (proceeds / shares) -- the only economically sound allocation for
    one sale event that consumed multiple lots. Gain per line = its
    allocated proceeds minus its already-allocated cost_basis. Term
    classification compares each line's acquired_date against its own
    disposal's disposal_date via _is_long_term. An empty disposal list
    returns zero totals, never an error.
    """
    per_line = []
    lt_gain = st_gain = 0.0
    for disposal in disposals:
        total_shares = disposal["shares"]
        per_share_proceeds = disposal["proceeds"] / total_shares if total_shares else 0.0
        for line in disposal["lots"]:
            allocated_proceeds = per_share_proceeds * line["shares_used"]
            gain = allocated_proceeds - line["cost_basis"]
            term = "long_term" if _is_long_term(line["acquired_date"], disposal["disposal_date"]) else "short_term"
            per_line.append({
                "disposal_id": disposal["id"],
                "lot_id": line["lot_id"],
                "symbol": disposal["symbol"],
                "shares_used": line["shares_used"],
                "cost_basis": line["cost_basis"],
                "proceeds": round(allocated_proceeds, 2),
                "gain": round(gain, 2),
                "term": term,
                "disposal_date": disposal["disposal_date"],
                "acquired_date": line["acquired_date"],
            })
            if term == "long_term":
                lt_gain += gain
            else:
                st_gain += gain
    return {
        "lines": per_line,
        "long_term_gain": round(lt_gain, 2),
        "short_term_gain": round(st_gain, 2),
        "total_gain": round(lt_gain + st_gain, 2),
    }
