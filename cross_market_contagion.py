"""Cross-market contagion tracking (FSI L5, world model) -- rolling
correlation between SPY and four major international equity ETFs (EEM
emerging markets, EWJ Japan, EWG Germany, FXI China).

Distinct from the already-shipped intra-app correlation matrix
(correlation_engine.py, tracks correlation *within* this app's own
watchlist/portfolio tickers) -- this module tracks US-vs-international
co-movement specifically, the textbook "when EM debt moves, what follows?"
world-model question named in MISSION.md's L5 list.

Uses market_data.fetch_history (never yfinance.Ticker.history directly,
per project convention -- see project memory on the dividend tz-localize
crash).
"""
import statistics
import time

from market_data import fetch_history

_CACHE_TTL_S = 900  # 15 min, matching copper_gold_ratio.py/credit_spread.py
_cache: dict = {"computed_at": 0.0, "data": None}

BASKET = ("EEM", "EWJ", "EWG", "FXI")
_COUPLED_THRESHOLD = 0.5
_DECOUPLED_THRESHOLD = 0.1
_CONTAGION_MIN_COUPLED = 3


def _daily_returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1]]


def _classify(correlation: float) -> str:
    if correlation >= _COUPLED_THRESHOLD:
        return "coupled"
    if correlation <= _DECOUPLED_THRESHOLD:
        return "decoupled"
    return "normal"


def compute_cross_market_contagion() -> dict | None:
    """{"pairs": {"EEM": {"correlation": float, "regime": str}, ...},
    "coupled_count": int, "contagion_risk": bool}, or None if SPY's own
    history can't be fetched."""
    spy_history = fetch_history("SPY", period="2mo", interval="1d")
    if not spy_history:
        return None
    spy_closes = [r["close"] for r in spy_history]

    pairs = {}
    for symbol in BASKET:
        history = fetch_history(symbol, period="2mo", interval="1d")
        if not history:
            continue
        closes = [r["close"] for r in history]
        n = min(len(spy_closes), len(closes))
        if n < 21:
            continue
        spy_returns = _daily_returns(spy_closes[-n:])[-20:]
        sym_returns = _daily_returns(closes[-n:])[-20:]
        if len(spy_returns) < 20 or len(sym_returns) < 20:
            continue
        try:
            correlation = statistics.correlation(spy_returns, sym_returns)
        except statistics.StatisticsError:
            continue
        pairs[symbol] = {"correlation": round(correlation, 3), "regime": _classify(correlation)}

    if not pairs:
        return None

    coupled_count = sum(1 for p in pairs.values() if p["regime"] == "coupled")
    return {
        "pairs": pairs,
        "coupled_count": coupled_count,
        "contagion_risk": coupled_count >= _CONTAGION_MIN_COUPLED,
    }


def get_cross_market_contagion(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_cross_market_contagion()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
