"""VIX term-structure -- front-month vs back-month spread as a market-wide fear gauge.

Uses CBOE's four maturity-tenor VIX indices via yfinance (^VIX9D, ^VIX,
^VIX3M, ^VIX6M) -- same yfinance-for-index-data pattern as
options_data_client.py, and deliberately never touches Ticker.fast_info
(reliably crashes this dev environment, see project memory). Contango
(upward-sloping curve, VIX9D < VIX6M) is the calm/normal state;
backwardation (inverted, VIX9D > VIX6M) is a classic short-horizon fear
signal that has historically preceded or accompanied sharp equity
drawdowns. Read-only public index prices -- no new externally-writable
surface, same trust boundary as the app's existing yfinance usage.
"""
import time

import yfinance as yf

_TICKERS = ["^VIX9D", "^VIX", "^VIX3M", "^VIX6M"]
_BACKWARDATION_THRESHOLD_PCT = -3.0  # front > back by 3%+ -- inverted curve
_CONTANGO_THRESHOLD_PCT = 3.0

_CACHE_TTL_S = 3600  # 1h -- daily-granularity index levels, no need to refetch every market tick
_cache: dict = {"computed_at": 0.0, "data": None}


def _latest_close(ticker: str) -> float | None:
    hist = yf.Ticker(ticker).history(period="5d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


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
