"""Rolling cross-asset correlation matrix — 30-day, 90-day, and 180-day
Pearson correlations between tracked assets' daily returns.

Foundational L2 pattern: reveals when assets move together or diverge,
context for portfolio diversification, risk management, and detecting
market regime shifts (assets that normally diverge suddenly correlating is
itself a signal).
"""
import time

import pandas as pd

from market_data import fetch_history
from memory_store import store_correlation_matrix

WINDOWS = (30, 90, 180)
_MIN_OBSERVATIONS = 5  # below this, a correlation coefficient is noise, not signal


def _fetch_daily_closes(symbols: list[str], delay_s: float = 0.2) -> pd.DataFrame:
    series = {}
    for i, sym in enumerate(symbols):
        history = fetch_history(sym, period="1y", interval="1d")
        if history:
            closes = {h["time"][:10]: h["close"] for h in history}
            series[sym] = pd.Series(closes)
        if i < len(symbols) - 1:
            time.sleep(delay_s)
    if not series:
        return pd.DataFrame()
    # Index stays as "YYYY-MM-DD" strings rather than pd.to_datetime — ISO-8601
    # strings sort identically to their datetime equivalents, and this venv's
    # numpy/pandas combo segfaults on pd.to_datetime(df.index) (see PR notes).
    df = pd.DataFrame(series)
    return df.sort_index()


def calculate_rolling_correlation(symbols: list[str]) -> dict[int, list[dict]]:
    """Returns {window_days: [{"symbol_a", "symbol_b", "correlation"}, ...]}.

    Each window's pairs use that window's trailing daily-return observations
    (~30, ~90, or ~180 trading days of the fetched 1-year history). A window
    is omitted entirely if there isn't enough overlapping data for any pair.
    """
    df = _fetch_daily_closes(symbols)
    if df.empty or len(df.columns) < 2:
        return {}

    returns = df.pct_change().dropna(how="all")
    results: dict[int, list[dict]] = {}

    for window in WINDOWS:
        windowed = returns.tail(window)
        if len(windowed) < _MIN_OBSERVATIONS:
            continue
        corr = windowed.corr()
        cols = corr.columns.tolist()
        pairs = []
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                val = corr.loc[a, b]
                if pd.notna(val):
                    pairs.append({"symbol_a": a, "symbol_b": b, "correlation": round(float(val), 4)})
        if pairs:
            results[window] = pairs

    return results


def refresh_correlation_matrix(symbols: list[str]) -> dict[int, int]:
    """Compute and persist the rolling correlation matrix. Returns {window_days: pair_count}."""
    results = calculate_rolling_correlation(symbols)
    stored = {}
    for window, pairs in results.items():
        store_correlation_matrix(pairs, window)
        stored[window] = len(pairs)
    return stored
