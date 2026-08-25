"""VIX term-structure -- front-month vs back-month spread as a market-wide fear gauge.

Uses CBOE's four maturity-tenor VIX indices (^VIX9D, ^VIX, ^VIX3M, ^VIX6M)
via portfolio_risk._daily_closes -- same cross-module reuse precedent as
divergence_radar.py, which already fetches these exact tickers this way.
Deliberately does NOT call yfinance.Ticker.history() directly: this
module originally did, and it reliably segfaults (exit 139) even on these
non-dividend index tickers, contradicting the narrower "dividend-paying
tickers only" framing in project memory -- confirmed live 2026-07-31 via
a bare repro (yf.Ticker("^VIX").history(period="5d")). SIGSEGV is not
catchable, so the per-ticker try/except in compute_vix_term_structure()
below was never actually protecting against it. _daily_closes() already
goes through market_data.fetch_history()'s pure-JSON _chart() path (no
pandas involved) plus gets a free 12h shared cache and Yahoo-rate-limit
staggering for free. Contango (upward-sloping curve, VIX9D < VIX6M) is
the calm/normal state; backwardation (inverted, VIX9D > VIX6M) is a
classic short-horizon fear signal that has historically preceded or
accompanied sharp equity drawdowns. Read-only public index prices -- no
new externally-writable surface, same trust boundary as the app's
existing yfinance usage.
"""
import time

from portfolio_risk import _daily_closes

_TICKERS = ["^VIX9D", "^VIX", "^VIX3M", "^VIX6M"]
_BACKWARDATION_THRESHOLD_PCT = -3.0  # front > back by 3%+ -- inverted curve
_CONTANGO_THRESHOLD_PCT = 3.0

_CACHE_TTL_S = 3600  # 1h -- daily-granularity index levels, no need to refetch every market tick
_cache: dict = {"computed_at": 0.0, "data": None}


def _latest_close(ticker: str) -> float | None:
    closes = _daily_closes(ticker)
    if not closes:
        return None
    return closes[max(closes)]


def compute_vix_term_structure() -> dict | None:
    """{"vix9d", "vix", "vix3m", "vix6m", "front_back_spread_pct", "regime"}
    (regime is "contango"/"backwardation"/"flat"), or None if the front/back
    tenors can't be fetched (Yahoo outage) -- caller should treat that as
    "no data", not fabricate a reading."""
    closes = {}
    for ticker in _TICKERS:
        try:
            closes[ticker] = _latest_close(ticker)
        except Exception as e:
            print(f"[VixTermStructure] {ticker} fetch failed: {e}")
            closes[ticker] = None

    front, back = closes.get("^VIX9D"), closes.get("^VIX6M")
    if front is None or back is None or front == 0:
        return None

    spread_pct = (back - front) / front * 100
    if spread_pct <= _BACKWARDATION_THRESHOLD_PCT:
        regime = "backwardation"
    elif spread_pct >= _CONTANGO_THRESHOLD_PCT:
        regime = "contango"
    else:
        regime = "flat"

    return {
        "vix9d": closes.get("^VIX9D"),
        "vix": closes.get("^VIX"),
        "vix3m": closes.get("^VIX3M"),
        "vix6m": closes.get("^VIX6M"),
        "front_back_spread_pct": round(spread_pct, 2),
        "regime": regime,
    }


def get_vix_term_structure(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_vix_term_structure()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
