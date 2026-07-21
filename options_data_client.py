"""Options chain aggregator -- put/call ratio and ~30-day ATM implied volatility.

Uses the yfinance package for options-chain data specifically: production's
own market_data.py talks to Yahoo's chart/quote endpoints directly via
requests (see its module docstring-equivalent comments), but Yahoo's options
endpoint is undocumented and not worth reverse-engineering when yfinance
(already an installed but otherwise-unused project dependency) exposes it
directly via Ticker.option_chain().

A high put/call ratio signals bearish positioning/hedging; elevated ATM IV
signals the market is pricing a bigger expected move. Free, no API key.
"""
import time
from datetime import date, datetime

import yfinance as yf

from memory_store import insert_options_data

_TARGET_DTE_DAYS = 30  # "30-day" ATM IV, per proposal spec


def _nearest_expiration(expirations: tuple, target_days: int = _TARGET_DTE_DAYS) -> str | None:
    if not expirations:
        return None
    today = date.today()

    def _dte_gap(exp: str) -> int:
        return abs((datetime.strptime(exp, "%Y-%m-%d").date() - today).days - target_days)

    return min(expirations, key=_dte_gap)


def fetch_options_snapshot(ticker: str, underlying_price: float | None = None) -> dict | None:
    """Aggregate put/call volume+OI ratio and ATM IV for the expiration nearest
    30 days out. Returns None for tickers with no listed options (crypto, most
    ASX symbols, some small caps) or an empty/unavailable chain.

    underlying_price should come from the app's own already-fetched quote
    (market_data.py / main.py's _quotes_cache) -- yfinance's own Ticker.fast_info
    price lookup makes a separate network call per symbol that's both wasteful
    (the app already has a fresh quote) and, observed live in this environment,
    unreliable enough to abort the whole process. ATM IV is simply omitted
    (still None) when no price is supplied, rather than fetched a second way."""
    try:
        t = yf.Ticker(ticker)
        exp = _nearest_expiration(t.options)
        if not exp:
            return None

        chain = t.option_chain(exp)
        calls, puts = chain.calls, chain.puts
        if calls.empty and puts.empty:
            return None

        call_vol = float(calls["volume"].fillna(0).sum())
        put_vol = float(puts["volume"].fillna(0).sum())
        call_oi = float(calls["openInterest"].fillna(0).sum())
        put_oi = float(puts["openInterest"].fillna(0).sum())

        pc_volume_ratio = round(put_vol / call_vol, 3) if call_vol > 0 else None
        pc_oi_ratio = round(put_oi / call_oi, 3) if call_oi > 0 else None

        atm_iv = _atm_iv_pct(underlying_price, calls, puts)

        return {
            "symbol": ticker,
            "expiration": exp,
            "put_call_volume_ratio": pc_volume_ratio,
            "put_call_oi_ratio": pc_oi_ratio,
            "atm_iv_pct": atm_iv,
        }
    except Exception as e:
        print(f"[Options] fetch_options_snapshot({ticker}) failed: {e}")
        return None


def _atm_iv_pct(price: float | None, calls, puts) -> float | None:
    """ATM IV = average of the call's and put's implied vol at the strike
    closest to the current price -- either side alone is noisier due to skew."""
    if not price or calls.empty:
        return None

    calls = calls.copy()
    calls["dist"] = (calls["strike"] - price).abs()
    ivs = [calls.loc[calls["dist"].idxmin(), "impliedVolatility"]]

    if not puts.empty:
        puts = puts.copy()
        puts["dist"] = (puts["strike"] - price).abs()
        ivs.append(puts.loc[puts["dist"].idxmin(), "impliedVolatility"])

    ivs = [v for v in ivs if v and v > 0]
    return round(sum(ivs) / len(ivs) * 100, 2) if ivs else None


def refresh_options_data(tickers: list[str], quotes: dict | None = None, delay_s: float = 1.0) -> int:
    """Fetch and store a snapshot per ticker. `quotes` is the app's already-fetched
    {symbol: {"price": ...}} cache, used for ATM strike selection -- see
    fetch_options_snapshot's docstring for why this isn't refetched here.
    Returns count stored."""
    quotes = quotes or {}
    stored = 0
    for i, sym in enumerate(tickers):
        price = (quotes.get(sym) or {}).get("price")
        data = fetch_options_snapshot(sym, underlying_price=price)
        if data:
            insert_options_data(
                sym, data["expiration"], data["put_call_volume_ratio"],
                data["put_call_oi_ratio"], data["atm_iv_pct"],
            )
            stored += 1
        if i < len(tickers) - 1:
            time.sleep(delay_s)
    return stored
