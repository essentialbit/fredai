"""Self-optimizing technical-indicator parameter tuning (FSI L3).

Grid-searches a small, bounded set of RSI and moving-average-cross
parameter combinations per ticker against trailing 1y daily history,
scoring each combo by how often it would have called the right 5-day
forward-return direction. Best-scoring combo per ticker per indicator is
persisted to optimized_params -- a starting point for technical_alerts.py
to eventually consult instead of its current hardcoded defaults, not
wired into the live alert engine by this change.

Grids are deliberately small (9 RSI combos, 3 MA combos) rather than
open-ended -- this runs daily across the whole watchlist/portfolio
universe, and 1y of daily closes is not enough data to justify a finer
search without overfitting.
"""
from market_data import fetch_history
from memory_store import upsert_optimized_params

_RSI_PERIODS = (7, 14, 21)
_RSI_BANDS = ((20, 80), (25, 75), (30, 70))
_MA_PAIRS = ((5, 20), (10, 50), (20, 100))

_FORWARD_DAYS = 5


def _closes(ticker: str) -> list[float]:
    history = fetch_history(ticker, period="1y", interval="1d")
    return [r["close"] for r in history if r.get("close") is not None]


def _rsi_series(closes: list[float], period: int) -> list[float | None]:
    """RSI at every index >= period, None before that (not enough history)."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    for i in range(period, len(closes)):
        window = closes[i - period:i + 1]
        gains, losses = [], []
        for j in range(1, len(window)):
            diff = window[j] - window[j - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100 - (100 / (1 + rs))
    return out


def _score_rsi(closes: list[float], period: int, oversold: int, overbought: int) -> tuple[float, int]:
    """Hit-rate: at each oversold/overbought crossing, does price move in
    the implied direction over the next _FORWARD_DAYS bars? Returns
    (hit_rate, sample_size)."""
    rsi = _rsi_series(closes, period)
    hits, total = 0, 0
    for i in range(len(closes) - _FORWARD_DAYS):
        r = rsi[i]
        if r is None:
            continue
        if r <= oversold:
            expected = "up"
        elif r >= overbought:
            expected = "down"
        else:
            continue
        actual = "up" if closes[i + _FORWARD_DAYS] > closes[i] else "down"
        total += 1
        if actual == expected:
            hits += 1
    return (hits / total if total else 0.0), total


def _score_ma_cross(closes: list[float], short: int, long: int) -> tuple[float, int]:
    """Hit-rate: after a short/long MA crossover, does price move in the
    crossover's implied direction over the next _FORWARD_DAYS bars?"""
    if len(closes) < long + _FORWARD_DAYS + 1:
        return 0.0, 0
    hits, total = 0, 0
    prev_signal = None
    for i in range(long, len(closes) - _FORWARD_DAYS):
        short_ma = sum(closes[i - short + 1:i + 1]) / short
        long_ma = sum(closes[i - long + 1:i + 1]) / long
        signal = "above" if short_ma > long_ma else "below"
        if prev_signal is not None and signal != prev_signal:
            expected = "up" if signal == "above" else "down"
            actual = "up" if closes[i + _FORWARD_DAYS] > closes[i] else "down"
            total += 1
            if actual == expected:
                hits += 1
        prev_signal = signal
    return (hits / total if total else 0.0), total


def optimize_ticker(ticker: str) -> dict:
    """Grid-search both indicator families for one ticker, persist the
    best-scoring combo for each, return what was found. {} if there's not
    enough history to backtest against."""
    closes = _closes(ticker)
    if len(closes) < 30:
        return {}

    best_rsi, best_rsi_score, best_rsi_n = None, -1.0, 0
    for period in _RSI_PERIODS:
        for oversold, overbought in _RSI_BANDS:
            score, n = _score_rsi(closes, period, oversold, overbought)
            if n >= 5 and score > best_rsi_score:
                best_rsi = {"period": period, "oversold": oversold, "overbought": overbought}
                best_rsi_score, best_rsi_n = score, n

    best_ma, best_ma_score, best_ma_n = None, -1.0, 0
    for short, long in _MA_PAIRS:
        score, n = _score_ma_cross(closes, short, long)
        if n >= 3 and score > best_ma_score:
            best_ma = {"short": short, "long": long}
            best_ma_score, best_ma_n = score, n

    result = {}
    if best_rsi:
        upsert_optimized_params(ticker, "rsi", best_rsi, round(best_rsi_score, 4), best_rsi_n)
        result["rsi"] = {"params": best_rsi, "score": round(best_rsi_score, 4), "sample_size": best_rsi_n}
    if best_ma:
        upsert_optimized_params(ticker, "ma_cross", best_ma, round(best_ma_score, 4), best_ma_n)
        result["ma_cross"] = {"params": best_ma, "score": round(best_ma_score, 4), "sample_size": best_ma_n}
    return result


def optimize_universe(tickers: list[str]) -> dict:
    """Run optimize_ticker across a list of symbols, returns {ticker: result}
    skipping ones with too little history rather than erroring."""
    out = {}
    for t in tickers:
        try:
            r = optimize_ticker(t)
            if r:
                out[t] = r
        except Exception as e:
            print(f"[ParamOptimizer] {t} error: {e}")
    return out
