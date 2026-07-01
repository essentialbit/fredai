import json
import os
import time
import requests
from datetime import datetime, timezone
from config import WATCHLIST, DISPLAY_SYMBOLS

_cache: dict = {}

_DISK_CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "price_cache.json")
_DISK_CACHE_MAX_AGE_S = 4 * 3600  # reuse disk cache if < 4h old

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_BASE2 = "https://query2.finance.yahoo.com/v8/finance/chart"
_BATCH_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

_session: requests.Session | None = None
_crumb: str | None = None
_session_ts: float = 0
_SESSION_TTL = 3600  # refresh cookies+crumb every hour


def _get_session() -> tuple[requests.Session, str]:
    """Return (session_with_cookies, crumb). Refreshes if > 1h old."""
    global _session, _crumb, _session_ts
    if _session and _crumb and (time.time() - _session_ts) < _SESSION_TTL:
        return _session, _crumb
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        s.get("https://finance.yahoo.com/", timeout=10)  # seeds cookies
        r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if r.status_code == 200 and r.text.strip():
            _session, _crumb, _session_ts = s, r.text.strip(), time.time()
            return _session, _crumb
    except Exception:
        pass
    # Fallback: bare session without crumb (still works on unblocked IPs sometimes)
    _session, _crumb, _session_ts = s, "", time.time()
    return _session, _crumb


def _load_disk_cache() -> dict:
    try:
        with open(_DISK_CACHE_PATH) as f:
            data = json.load(f)
        saved_at = data.get("_saved_at", 0)
        age = time.time() - saved_at
        if age < _DISK_CACHE_MAX_AGE_S:
            quotes = {k: v for k, v in data.items() if k != "_saved_at"}
            if quotes:
                print(f"[Market] Loaded {len(quotes)} prices from disk cache (age {age/60:.0f}m)")
                return quotes
    except Exception:
        pass
    return {}


def _save_disk_cache(quotes: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_DISK_CACHE_PATH), exist_ok=True)
        with open(_DISK_CACHE_PATH, "w") as f:
            json.dump({"_saved_at": time.time(), **quotes}, f)
    except Exception:
        pass


def _fetch_batch(symbols: list[str]) -> dict:
    """Single Yahoo Finance v7 batch call for up to 100 symbols. Returns price dict."""
    sess, crumb = _get_session()
    chunk_results = {}
    # Yahoo v7 handles ~100 symbols per request
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        for attempt in range(3):
            try:
                params = {
                    "symbols": ",".join(chunk),
                    "fields": "regularMarketPrice,regularMarketChangePercent,regularMarketPreviousClose,shortName,currency",
                }
                if crumb:
                    params["crumb"] = crumb
                r = sess.get(
                    _BATCH_URL,
                    params=params,
                    timeout=20,
                )
                if r.status_code == 429:
                    wait = 15 * (2 ** attempt)
                    print(f"[Market] 429 rate-limit — waiting {wait}s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                items = r.json().get("quoteResponse", {}).get("result", [])
                for q in items:
                    sym = q.get("symbol", "")
                    price = float(q.get("regularMarketPrice") or 0)
                    prev = float(q.get("regularMarketPreviousClose") or price)
                    change_pct = float(q.get("regularMarketChangePercent") or 0)
                    change = price - prev
                    currency = "AUD" if sym.endswith(".AX") else q.get("currency", "USD")
                    chunk_results[sym] = {
                        "symbol": sym,
                        "name": DISPLAY_SYMBOLS.get(sym, q.get("shortName", sym)),
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_pct": round(change_pct, 2),
                        "prev_close": round(prev, 2),
                        "currency": currency,
                        "updated": datetime.now(timezone.utc).isoformat(),
                    }
                break
            except Exception as e:
                if attempt == 2:
                    print(f"[Market] Batch fetch failed: {e}")
    return chunk_results

SECTORS = {
    "Technology": ["AAPL", "NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "Finance": ["JPM", "GS", "BAC"],
    "Index ETF": ["SPY", "QQQ"],
    "Crypto": ["BTC-USD", "ETH-USD"],
    "ASX Banks": ["CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX"],
    "ASX Mining": ["BHP.AX", "RIO.AX", "FMG.AX"],
    "ASX Tech": ["WTC.AX", "XRO.AX", "REA.AX"],
    "ASX Healthcare": ["CSL.AX", "COH.AX"],
    "ASX Energy": ["WDS.AX", "STO.AX"],
}

_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "1d": "1d", "1wk": "1wk",
}

_RANGE_MAP = {
    "1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo",
    "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y",
}


def _chart(symbol: str, interval: str = "1d", period: str = "5d") -> dict | None:
    interval = _INTERVAL_MAP.get(interval, interval)
    period = _RANGE_MAP.get(period, period)
    for base in (_BASE, _BASE2):
        for attempt in range(3):
            try:
                r = requests.get(
                    f"{base}/{symbol}?interval={interval}&range={period}",
                    headers=_HEADERS, timeout=12,
                )
                if r.status_code == 429:
                    time.sleep(10 * (2 ** attempt))
                    continue
                r.raise_for_status()
                result = r.json().get("chart", {}).get("result")
                if result:
                    return result[0]
                break
            except Exception:
                break
    return None


def fetch_quotes(symbols: list[str] = None) -> dict:
    target = symbols or WATCHLIST

    # For full-watchlist fetches, try disk cache first
    if not symbols:
        cached = _load_disk_cache()
        if cached:
            return cached

    # Batch fetch (single request for all symbols)
    results = _fetch_batch(target)

    # Per-symbol chart fallback for anything the batch missed
    missing = [s for s in target if s not in results]
    for sym in missing:
        try:
            time.sleep(0.5)
            data = _chart(sym, "1d", "5d")
            if not data:
                continue
            meta = data["meta"]
            price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
            prev = float(meta.get("previousClose") or price)
            if prev == 0:
                prev = price
            change = price - prev
            change_pct = (change / prev * 100) if prev else 0
            currency = "AUD" if sym.endswith(".AX") else "USD"
            results[sym] = {
                "symbol": sym,
                "name": DISPLAY_SYMBOLS.get(sym, sym),
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "prev_close": round(prev, 2),
                "currency": currency,
                "updated": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            print(f"[Market] Chart fallback failed for {sym}: {e}")

    if results and not symbols:
        _save_disk_cache(results)

    return results


def fetch_history(symbol: str, period: str = "5d", interval: str = "30m") -> list[dict]:
    try:
        data = _chart(symbol, interval, period)
        if not data:
            return []
        timestamps = data.get("timestamp", [])
        quote = data.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        records = []
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue
            dt = datetime.utcfromtimestamp(ts).isoformat() + "Z"
            records.append({
                "time": dt,
                "open": round(float(opens[i] or closes[i]), 2),
                "high": round(float(highs[i] or closes[i]), 2),
                "low": round(float(lows[i] or closes[i]), 2),
                "close": round(float(closes[i]), 2),
                "volume": int(volumes[i] or 0) if i < len(volumes) else 0,
            })
        return records
    except Exception as e:
        print(f"[Market] History failed for {symbol}: {e}")
        return []


def get_sector_snapshot(quotes: dict) -> list[dict]:
    rows = []
    for sector, syms in SECTORS.items():
        for sym in syms:
            q = quotes.get(sym)
            if q:
                rows.append({
                    "sector": sector,
                    "symbol": sym,
                    "name": q["name"],
                    "change_pct": q["change_pct"],
                })
    return rows


def calculate_portfolio_value(holdings: list[dict], quotes: dict) -> dict:
    total_value = 0.0
    total_cost = 0.0
    positions = []
    for h in holdings:
        sym = h["symbol"]
        shares = float(h.get("shares", 0))
        avg_cost = float(h.get("avg_cost", 0))
        q = quotes.get(sym, {})
        price = q.get("price", avg_cost)
        value = shares * price
        cost = shares * avg_cost
        pnl = value - cost
        pnl_pct = (pnl / cost * 100) if cost else 0
        total_value += value
        total_cost += cost
        positions.append({
            "symbol": sym,
            "name": DISPLAY_SYMBOLS.get(sym, sym),
            "shares": shares,
            "avg_cost": avg_cost,
            "price": price,
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "change_pct": q.get("change_pct", 0),
        })
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": positions,
    }
